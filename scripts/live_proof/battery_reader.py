"""Section B — the accumulating battery-summary.json history reader (#840 scaffold).

The "Grading Health" section of the live-proof dashboard renders operator-legible
night-over-night trends from the ``battery-summary.json`` files the nightly M2 battery
writes (``tools/dispatch_harness/battery.py`` — :meth:`BatterySummary.to_dict`, schema
``battery-summary/v1``). This module ingests that history and normalizes each night into a
:class:`NightRecord` the generator renders.

WHAT IS ALWAYS PRESENT vs WHAT IS NEW (the honesty seam): every historical summary carries
``verdicts`` / ``hard_gates`` / ``reliability`` / ``guest_oracle_agreement``. The advisory
grading-health blocks are NEWER instruments that only appear once they run at battery close:

* ``failure_taxonomy`` (#827) — per-class failure counts + the night-over-night trend;
* ``green_integrity`` (#832) — grader-tampering GREEN→PARKED downgrades by fingerprint class;
* ``green_quality`` (#837) — A/B/C GREEN-quality bands + regressed/craft-residue tallies.

As of this scaffold NONE of the accumulated historical summaries carry those three blocks
(they predate the classifiers landing on main) — so Section B renders them with a labeled
"no data yet — first datapoint lands after a battery run with the classifiers wired" empty
state, while still charting the verdict/reliability/guest-agreement trends that ARE present.
This module NEVER fabricates a missing block; absence is surfaced as ``has_*=False``.

Deterministic, read-only, no network. Fail-soft: an unreadable/partial summary is skipped
with a recorded reason, never a crash.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BATTERY_DIR = Path("C:/Users/mrbla/agentic-setup/state/battery")

BATTERY_SUMMARY_SCHEMA = "battery-summary/v1"

# The verdict vocabulary (scorecard.py). Stable order = worst-severity-last for the stack.
VERDICT_ORDER: tuple[str, ...] = (
    "GREEN", "PARKED-HONEST", "RECOVERED", "STALLED", "FALSE-DONE",
)

# The #827 failure classes, stable order (failure_taxonomy.FAILURE_CLASSES).
FAILURE_CLASS_ORDER: tuple[str, ...] = (
    "ORACLE-DEFECT", "INTEGRATION-SEAM", "BLIND-FIX-LOOP",
    "DECOMPOSE-DOWNGRADE", "HARNESS-BUDGET", "UNCLASSIFIED",
)

# The #827 GREEN-side classes (failure_taxonomy.GREEN_CLASSES).
GREEN_CLASS_ORDER: tuple[str, ...] = (
    "GREEN-VERIFIED", "GREEN-PARTIAL", "GREEN-UNVERIFIED", "GREEN-GAMED",
)

# The #837 quality bands (green_quality.constants.BANDS).
BAND_ORDER: tuple[str, ...] = ("A", "B", "C")

# The #744 guest-oracle agreement vocabulary.
GUEST_AGREEMENT_ORDER: tuple[str, ...] = (
    "agree", "DIVERGENCE", "guest-not-run", "no-certificate",
)

_STAMP_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")


@dataclass
class NightRecord:
    """One night's normalized battery outcome for the trend charts."""

    label: str                      # the run-dir name, e.g. "night-20260711-000001"
    date: str                       # "YYYY-MM-DD" parsed from the label, or "" if unparseable
    path: str                       # the summary file that fed this record
    total: int = 0
    dry_run: bool = False
    verdicts: dict[str, int] = field(default_factory=dict)
    false_done: int = 0
    interventions: int = 0
    green: int = 0
    plan_graph_eligible: int = 0
    flat_queue: int = 0
    green_over_eligible: str = ""
    green_over_total: str = ""
    guest_agreement: dict[str, int] = field(default_factory=dict)

    # Advisory blocks — present only once the classifiers run at battery close.
    has_taxonomy: bool = False
    failure_classes: dict[str, int] = field(default_factory=dict)
    green_classes: dict[str, int] = field(default_factory=dict)
    unclassified_rate: str = ""

    has_green_integrity: bool = False
    integrity_downgraded: int = 0
    integrity_class_counts: dict[str, int] = field(default_factory=dict)

    has_green_quality: bool = False
    quality_bands: dict[str, int] = field(default_factory=dict)
    quality_regressed: int = 0
    quality_craft_residue: int = 0
    quality_mode: str = ""

    def oracle_coverage(self) -> tuple[int, int] | None:
        """Derived oracle-coverage over GREENs, from #827's green-class stamp: k = fully
        VERIFIED greens, n = all classified greens (VERIFIED + PARTIAL + UNVERIFIED, excluding
        GAMED which is an integrity concern). ``None`` when no taxonomy block exists yet —
        NEVER a fabricated number (the coverage % is honestly absent until #821/#827 stamp it)."""
        if not self.has_taxonomy:
            return None
        gc = self.green_classes
        verified = int(gc.get("GREEN-VERIFIED", 0) or 0)
        n = verified + int(gc.get("GREEN-PARTIAL", 0) or 0) + int(gc.get("GREEN-UNVERIFIED", 0) or 0)
        return (verified, n)

    def to_dict(self) -> dict:
        return {
            "label": self.label, "date": self.date, "path": self.path,
            "total": self.total, "dry_run": self.dry_run,
            "verdicts": self.verdicts,
            "false_done": self.false_done, "interventions": self.interventions,
            "green": self.green, "plan_graph_eligible": self.plan_graph_eligible,
            "flat_queue": self.flat_queue,
            "green_over_eligible": self.green_over_eligible,
            "green_over_total": self.green_over_total,
            "guest_agreement": self.guest_agreement,
            "has_taxonomy": self.has_taxonomy,
            "failure_classes": self.failure_classes,
            "green_classes": self.green_classes,
            "unclassified_rate": self.unclassified_rate,
            "has_green_integrity": self.has_green_integrity,
            "integrity_downgraded": self.integrity_downgraded,
            "integrity_class_counts": self.integrity_class_counts,
            "has_green_quality": self.has_green_quality,
            "quality_bands": self.quality_bands,
            "quality_regressed": self.quality_regressed,
            "quality_craft_residue": self.quality_craft_residue,
            "quality_mode": self.quality_mode,
        }


def _date_from_label(label: str) -> str:
    m = _STAMP_RE.search(label)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def find_summaries(battery_dir: Path) -> list[Path]:
    """Every ``battery-summary.json`` under *battery_dir*, sorted chronologically by the
    dated run-dir name (the naming convention sorts lexicographically = chronologically).
    Dry-run temp dirs elsewhere are not searched — only the campaign state root."""
    root = Path(battery_dir)
    if not root.is_dir():
        return []
    found = list(root.glob("**/battery-summary.json"))
    # Sort by the run-dir name (the parent, or grandparent when nested under scorecards/).

    def _sort_key(p: Path) -> str:
        parent = p.parent
        if parent.name == "scorecards":
            parent = parent.parent
        return parent.name

    return sorted(found, key=_sort_key)


def _run_dir_name(path: Path) -> str:
    parent = path.parent
    if parent.name == "scorecards":
        parent = parent.parent
    return parent.name


def read_night(path: Path) -> NightRecord | None:
    """Parse one ``battery-summary.json`` into a :class:`NightRecord`, or ``None`` if it is
    unreadable / not a battery summary. Fail-soft: a partial/legacy block is simply absent
    (``has_*=False``), never guessed."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != BATTERY_SUMMARY_SCHEMA:
        return None

    label = _run_dir_name(Path(path))
    rec = NightRecord(label=label, date=_date_from_label(label), path=str(path))
    rec.total = int(data.get("total", 0) or 0)
    rec.dry_run = bool(data.get("dry_run", False))

    verdicts = data.get("verdicts") or {}
    rec.verdicts = {v: int(verdicts.get(v, 0) or 0) for v in VERDICT_ORDER}

    hg = data.get("hard_gates") or {}
    rec.false_done = int(hg.get("false_done", 0) or 0)
    rec.interventions = int(hg.get("interventions_total", 0) or 0)

    rel = data.get("reliability") or {}
    rec.green = int(rel.get("green", 0) or 0)
    rec.plan_graph_eligible = int(rel.get("plan_graph_eligible", 0) or 0)
    rec.flat_queue = int(rel.get("flat_queue", 0) or 0)
    rec.green_over_eligible = str(rel.get("green_over_eligible", "") or "")
    rec.green_over_total = str(rel.get("green_over_total", "") or "")

    ga = data.get("guest_oracle_agreement") or {}
    rec.guest_agreement = {k: int(ga.get(k, 0) or 0) for k in GUEST_AGREEMENT_ORDER}

    # #827 — advisory failure taxonomy (present only after classify() ran at battery close).
    tax = data.get("failure_taxonomy")
    if isinstance(tax, dict) and tax.get("failure_classes"):
        rec.has_taxonomy = True
        fc = tax.get("failure_classes") or {}
        rec.failure_classes = {c: int(fc.get(c, 0) or 0) for c in FAILURE_CLASS_ORDER}
        gc = tax.get("green_classes") or {}
        rec.green_classes = {c: int(gc.get(c, 0) or 0) for c in GREEN_CLASS_ORDER}
        rec.unclassified_rate = str(tax.get("unclassified_rate", "") or "")

    # #832 — advisory earned-GREEN integrity tally.
    gi = data.get("green_integrity")
    if isinstance(gi, dict) and ("downgraded" in gi or gi.get("class_counts")):
        rec.has_green_integrity = True
        rec.integrity_downgraded = int(gi.get("downgraded", 0) or 0)
        cc = gi.get("class_counts") or {}
        rec.integrity_class_counts = {str(k): int(v or 0) for k, v in cc.items()}

    # #837 — advisory GREEN-quality band tally.
    gq = data.get("green_quality")
    if isinstance(gq, dict) and gq.get("audited") is not None and gq.get("bands"):
        rec.has_green_quality = True
        bands = gq.get("bands") or {}
        rec.quality_bands = {b: int(bands.get(b, 0) or 0) for b in BAND_ORDER}
        rec.quality_regressed = int(gq.get("regressed", 0) or 0)
        rec.quality_craft_residue = int(gq.get("craft_residue", 0) or 0)
        rec.quality_mode = str(gq.get("mode", "") or "")

    return rec


def read_history(battery_dir: Path | None = None, *, include_dry_run: bool = False) -> list[NightRecord]:
    """Every readable night, chronological (oldest→newest). Dry-run summaries are excluded
    by default (they model the system working, not a real capability measurement)."""
    root = Path(battery_dir) if battery_dir is not None else DEFAULT_BATTERY_DIR
    out: list[NightRecord] = []
    for path in find_summaries(root):
        rec = read_night(path)
        if rec is None:
            continue
        if rec.dry_run and not include_dry_run:
            continue
        out.append(rec)
    return out


@dataclass
class HistorySummary:
    """The whole-history roll-up the Section-B headline tiles render from."""

    nights: list[NightRecord]

    @property
    def count(self) -> int:
        return len(self.nights)

    @property
    def any_false_done(self) -> int:
        return sum(n.false_done for n in self.nights)

    @property
    def any_interventions(self) -> int:
        return sum(n.interventions for n in self.nights)

    @property
    def total_green(self) -> int:
        return sum(n.green for n in self.nights)

    @property
    def total_eligible(self) -> int:
        return sum(n.plan_graph_eligible for n in self.nights)

    @property
    def taxonomy_nights(self) -> int:
        return sum(1 for n in self.nights if n.has_taxonomy)

    @property
    def green_quality_nights(self) -> int:
        return sum(1 for n in self.nights if n.has_green_quality)

    @property
    def green_integrity_nights(self) -> int:
        return sum(1 for n in self.nights if n.has_green_integrity)

    @property
    def latest_date(self) -> str:
        for n in reversed(self.nights):
            if n.date:
                return n.date
        return ""


def summarize(nights: list[NightRecord]) -> HistorySummary:
    return HistorySummary(nights=nights)
