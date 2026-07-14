"""#837 §4.5 — calibrate the GREEN-audit against the operator's live-verify (measure, don't trust).

The jury (and the whole band) must be MEASURED against ground truth, not trusted on faith —
and the ground truth already exists: the operator's own accept/reject when he tries a GREEN
in his hands (the "what you got" card is where he renders it). As those verdicts accumulate,
we keep a small calibration set of ``(green_quality band/fields, operator accept/reject)``
pairs and report the audit's AGREEMENT RATE against it.

Two honest properties the dossier (and the LA principle) draw a hard line between:

* **The measurement half is a SAFE ADOPT — do it now.** Computing "how often did the audit's
  concern match the operator's verdict?" changes NOTHING about banking; it is pure evidence
  (it audits the auditor). It needs only that operator verdicts get recorded next to the
  scorecard — the recording seam below.
* **Tuning follows the data; AUTHORITY is the LA's.** The agreement thresholds and any
  per-lens weights are set from the calibration set once it is large enough — never guessed.
  And any move to let a band GATE banking (turn a lenient GREEN into a PARK) is a change to
  what the system can bank: it is ESCALATED to the LA with the calibrated design as the
  recommended mechanism, NEVER adopted silently. This module measures; it never gates.

The instrument ships as a STUB in the sense that the operator-verdict capture UI is a
separate limb (the card is where it will live); the recording + agreement math here are real
and ready, so the moment a verdict is captured the calibration set starts compounding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CALIBRATION_LOG_NAME = "green-quality-calibration.jsonl"

#: The operator's ground-truth disposition when he tried the GREEN in his hands.
OP_ACCEPT = "accept"
OP_REJECT = "reject"
OP_VERDICTS: frozenset[str] = frozenset({OP_ACCEPT, OP_REJECT})

#: The audit's coarse concern flag, derived from the band: A = no concern; B/C = concern.
#: (Deliberately coarse for the first calibration budget; a finer per-field agreement is a
#: data-driven refinement once the set is large — never a guess now.)
def band_flags_concern(band: str) -> bool:
    return str(band).upper() in ("B", "C")


@dataclass(frozen=True)
class CalibrationPair:
    """One ``(audit, operator)`` observation."""

    job_id: str
    run_id: str
    band: str
    operator_verdict: str  # OP_ACCEPT | OP_REJECT
    #: optional per-field snapshot (for the later, finer agreement analysis).
    fields: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {"job_id": self.job_id, "run_id": self.run_id, "band": self.band,
             "operator_verdict": self.operator_verdict}
        if self.fields:
            d["fields"] = self.fields
        return d


def record_pair(log_dir: Path, pair: CalibrationPair) -> bool:
    """Append one calibration observation to ``<log_dir>/green-quality-calibration.jsonl``.
    Returns True on success; fail-soft False on any I/O error (calibration is evidence — a
    write miss must never affect a battery night). This is the SAFE-ADOPT recording seam:
    call it when an operator accept/reject is captured for a GREEN."""
    if pair.operator_verdict not in OP_VERDICTS:
        return False
    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        with (path / CALIBRATION_LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(pair.to_dict(), ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def load_pairs(log_dir: Path) -> list[CalibrationPair]:
    """Read every recorded calibration observation (fail-soft → [] on a missing/broken log)."""
    path = Path(log_dir) / CALIBRATION_LOG_NAME
    out: list[CalibrationPair] = []
    try:
        if not path.is_file():
            return []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            verdict = str(d.get("operator_verdict", ""))
            if verdict not in OP_VERDICTS:
                continue
            out.append(CalibrationPair(
                job_id=str(d.get("job_id", "")), run_id=str(d.get("run_id", "")),
                band=str(d.get("band", "")), operator_verdict=verdict,
                fields=d.get("fields") if isinstance(d.get("fields"), dict) else None,
            ))
    except OSError:
        return []
    return out


def agreement_rate(pairs: list[CalibrationPair]) -> dict:
    """The audit-vs-operator agreement report (REPORTED, never gated). Coarse first metric:
    the audit's band-concern flag (A → no concern; B/C → concern) vs the operator's verdict
    (accept → no concern; reject → concern) — the fraction that agree, plus the per-band
    accept/reject breakdown that the later per-field tuning reads.

    ``agreement`` is ``"k/n"`` (honest denominator); ``None``-safe on an empty set."""
    n = len(pairs)
    agree = 0
    by_band: dict[str, dict[str, int]] = {}
    for p in pairs:
        band = str(p.band).upper() or "?"
        bucket = by_band.setdefault(band, {OP_ACCEPT: 0, OP_REJECT: 0})
        bucket[p.operator_verdict] = bucket.get(p.operator_verdict, 0) + 1
        audit_concern = band_flags_concern(p.band)
        operator_concern = p.operator_verdict == OP_REJECT
        if audit_concern == operator_concern:
            agree += 1
    return {
        "schema": "green-quality-calibration/v1",
        "pairs": n,
        "agreement": f"{agree}/{n}" if n else "0/0",
        "by_band": by_band,
        # The honest posture until the set is large: high abstention / advisory-only. The
        # thresholds that would ever let this GATE are an LA decision, set from THIS data.
        "gating": "advisory-only (agreement is reported; any authority-over-banking is an LA decision)",
    }
