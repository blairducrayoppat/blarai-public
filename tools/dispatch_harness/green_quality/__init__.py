"""#837 QUALITY-17 — the GREEN-quality audit (advisory, never verdict-changing).

The QUALITY companion to #832's earned-GREEN INTEGRITY audit (`green_audit.py`): #832 gates
grader-tampering (verdict-changing, GREEN→PARKED), this package reads the DISTINCT quality
axis (fragile / ugly / unusable) advisory-only, composing BENEATH #832's gate. At battery
close, for every job that still banks GREEN after the integrity gate, this package runs:

* **Layer 1** (:mod:`.layer1`) — the deterministic floor: the archetype-regression probe
  (diff the GREEN's observable behaviour against the last archived GREEN of the same card),
  craft lints (dead scaffold / stale README / no runnable entry point), and advisory ruff.
  This layer alone would have caught the B2 tokenizer regression the flat GREEN scoreboard
  missed. No model, seconds, ecosystem-agnostic where it can be.
* **Layer 2** (:mod:`.jury`) — the diverse small-model jury: a compact, grammar-constrained
  enum rubric scored by 3 lens-diverse 14B jurors, per-field majority, abstain-on-disagreement.
  A GPU slot, so it is DORMANT by default (``jury=None``) and a supervised live-verify item.
* **The band** (:mod:`.band`) — A/B/C computed by a DETERMINISTIC FORMULA over the scored
  fields (the model never renders the band).
* **The card** (:mod:`.card`) — the surface-aware plain-language "what you got" caveat, the
  non-technical operator's only window into GREEN quality.

Two invariants are enforced in code, not merely documented:

* **ADVISORY / NEVER verdict-changing.** The audit writes ONLY the reserved
  ``evidence.green_quality_*`` keys; :func:`audit_greens` snapshots ``(verdict, attribution)``
  per card and restores + flags any mutation. The scorecard schema additionally makes a
  band→verdict physically inexpressible. With a noisy small-model judge this is doubly
  load-bearing (#740 c.1721).
* **FAIL-SOFT.** A missing repo, an unrunnable probe, an absent jury — each degrades a
  finding, never sinks the night. The whole entry point is wrapped so a green-quality fault
  leaves an empty block and the battery summary still writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from tools.dispatch_harness.scorecard import Scorecard, VERDICT_GREEN, write_scorecard

from . import band as _band
from . import calibration as _calibration
from . import card as _card
from . import jury as _jury
from . import layer1 as _layer1
from .constants import (
    BANDS,
    EV_BAND,
    EV_BAD_INPUT,
    EV_CARD,
    EV_CORRECTNESS,
    EV_DEAD_SCAFFOLD,
    EV_FINDINGS,
    EV_MODE,
    EV_NAMING,
    EV_REGRESSED,
    EV_RUNNABLE,
    EV_UNCERTAIN,
    EVIDENCE_VALUE_CAP,
    FIELD_BAD_INPUT,
    FIELD_CORRECTNESS_PROBE,
    FIELD_NAMING_STRUCTURE,
    FIELD_RUNNABLE_SURFACE,
    GREEN_QUALITY_SCHEMA,
    GREEN_QUALITY_SIDECAR_NAME,
    MODE_DET_JURY,
    MODE_DET_ONLY,
)

# Re-exports (the package's public surface).
from .band import compute_band  # noqa: E402,F401
from .calibration import CalibrationPair, agreement_rate, record_pair  # noqa: E402,F401
from .card import WhatYouGotCard, build_card  # noqa: E402,F401
from .jury import Juror, JuryResult, build_default_jury, run_jury  # noqa: E402,F401
from .layer1 import Layer1Result, ProbeSet, audit_layer1, find_reference_green, load_probe_set  # noqa: E402,F401

#: Where the per-job probe-sets live (beside the battery cards; the frozen cards stay pristine).
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROBE_DIR = _REPO_ROOT / "evals" / "battery" / "green_quality"


def _clip(text: str) -> str:
    """One line, capped — the scorecard-evidence S6 discipline."""
    import re
    return re.sub(r"\s+", " ", str(text)).strip()[:EVIDENCE_VALUE_CAP]


@dataclass
class GreenAuditResult:
    """The full audit of one GREEN — the sidecar payload + the evidence stamp source."""

    job_id: str
    run_id: str
    repo: str
    surface: str
    band: str
    mode: str
    layer1: Layer1Result
    jury: Optional[JuryResult]
    card: WhatYouGotCard
    reference_green: Optional[str]
    c_reasons: list[str] = field(default_factory=list)
    b_reasons: list[str] = field(default_factory=list)

    def to_sidecar(self) -> dict:
        """The ``green-quality.json`` payload (structural — pointers + short statuses). This is
        this audit's OWN artifact, distinct from #832's ``green-audit.json`` integrity sidecar;
        it is not read by #827 and is never a gaming fingerprint."""
        jr = self.jury
        return {
            "schema": GREEN_QUALITY_SCHEMA,
            "advisory": True,
            "job_id": self.job_id,
            "run_id": self.run_id,
            "repo": self.repo,
            "surface": self.surface,
            "band": self.band,
            "mode": self.mode,
            "regressed": self.layer1.regression.regressed,
            "changed": self.layer1.regression.changed,
            "regression_detail": _clip(self.layer1.regression.detail),
            "regression_measured": self.layer1.regression.measured,
            "reference_green": self.reference_green or "",
            "craft": {
                "dead_scaffold": self.layer1.dead_scaffold.flagged,
                "stale_readme": self.layer1.stale_readme.flagged,
                "no_entry_point": self.layer1.no_entry_point.flagged,
                "ruff_findings": self.layer1.ruff_findings,
            },
            "layer1_findings": [_clip(f) for f in self.layer1.findings()],
            "jury": None if jr is None else {
                "scores": dict(jr.scores),
                "uncertain": list(jr.uncertain),
                "juror_count": jr.juror_count,
            },
            "band_reasons": {"c": [_clip(r) for r in self.c_reasons],
                             "b": [_clip(r) for r in self.b_reasons]},
            "card": {
                "headline": self.card.headline,
                "run_hint": self.card.run_hint,
                "caveat": self.card.caveat,
                "rendered": self.card.render(),
            },
        }

    def evidence_stamp(self, sidecar_pointer: str) -> dict:
        """The reserved ``green_quality_*`` evidence keys (the advisory stamp on the scorecard).
        ONLY these keys are ever written — never a verdict/attribution."""
        stamp: dict = {
            EV_BAND: self.band,
            EV_MODE: self.mode,
            EV_CARD: self.card.to_evidence(),
            EV_FINDINGS: sidecar_pointer,
        }
        if self.layer1.regression.regressed:
            stamp[EV_REGRESSED] = _clip(self.layer1.regression.detail)
        if self.layer1.dead_scaffold.flagged:
            stamp[EV_DEAD_SCAFFOLD] = "residue"
        jr = self.jury
        if jr is not None:
            for field_name, key in (
                (FIELD_RUNNABLE_SURFACE, EV_RUNNABLE),
                (FIELD_BAD_INPUT, EV_BAD_INPUT),
                (FIELD_NAMING_STRUCTURE, EV_NAMING),
                (FIELD_CORRECTNESS_PROBE, EV_CORRECTNESS),
            ):
                v = jr.value(field_name)
                if v is not None:
                    stamp[key] = v
            if jr.uncertain:
                stamp[EV_UNCERTAIN] = list(jr.uncertain)
        return stamp


def _resolve_current_repo(
    repo_slug: str, out_dir: Optional[Path], projects_dir: Optional[Path]
) -> Optional[Path]:
    """The GREEN's shipped repo: the just-archived copy under the run root if present, else
    the live sandbox project dir. ``None`` when neither exists (Layer 1 then runs unmeasured)."""
    for base in (out_dir, ):
        if base is not None:
            cand = Path(base) / "repos-archived" / repo_slug
            if cand.is_dir():
                return cand
    if projects_dir is not None:
        cand = Path(projects_dir) / repo_slug
        if cand.is_dir():
            return cand
    return None


def _jury_subject(repo: Optional[Path], layer1: Layer1Result) -> str:
    """The text a juror scores. Offline/det-only this is a compact repo summary; the LIVE
    (GPU-window) subject is the critic seam's merged-diff gather — the same swap the critic
    already owns. Kept small (a 14B degrades on long context)."""
    parts = [f"repo: {repo if repo else 'unknown'}", f"surface: {layer1.surface}"]
    findings = layer1.findings()
    if findings:
        parts.append("deterministic findings: " + "; ".join(findings[:6]))
    return "\n".join(parts)


def audit_green(
    sc: Scorecard,
    *,
    runs_dir: "str | Path | None" = None,
    out_dir: "str | Path | None" = None,
    projects_dir: "str | Path | None" = None,
    archive_root: "str | Path | None" = None,
    probe_dir: "str | Path | None" = None,
    surface: str = "",
    jurors: Optional[list[Juror]] = None,
) -> Optional[GreenAuditResult]:
    """Audit ONE GREEN scorecard, or ``None`` if it is not a GREEN. Pure of side effects on
    the scorecard (stamping is :func:`audit_greens`'s job); returns the full result so a
    caller can stamp, write the sidecar, and render the card."""
    if sc.verdict != VERDICT_GREEN:
        return None
    repo_slug = str(sc.repo or "")
    out_path = Path(out_dir) if out_dir else None
    arch_root = Path(archive_root) if archive_root else (out_path.parent if out_path else None)
    probe_root = Path(probe_dir) if probe_dir else DEFAULT_PROBE_DIR

    probe_set = _layer1.load_probe_set(sc.job_id, probe_root)
    current_repo = _resolve_current_repo(repo_slug, out_path, Path(projects_dir) if projects_dir else None)
    reference_repo = _layer1.find_reference_green(
        arch_root, sc.job_id, repo_slug, exclude_night=out_path
    )
    surf = surface or (probe_set.surface if probe_set else "")

    l1 = audit_layer1(
        current_repo if current_repo else Path(repo_slug),
        reference_repo, probe_set, surface=surf,
    )

    jury_result: Optional[JuryResult] = None
    mode = MODE_DET_ONLY
    if jurors:
        jury_result = run_jury(jurors, _jury_subject(current_repo, l1))
        mode = MODE_DET_JURY

    chosen_band, c_reasons, b_reasons = _band.band_reasons(l1, jury_result)
    the_card = build_card(sc.job_id, surf, chosen_band, l1,
                          jury_uncertain=jury_result.uncertain if jury_result else None)

    return GreenAuditResult(
        job_id=sc.job_id, run_id=sc.run_id, repo=repo_slug, surface=surf,
        band=chosen_band, mode=mode, layer1=l1, jury=jury_result, card=the_card,
        reference_green=str(reference_repo) if reference_repo else None,
        c_reasons=c_reasons, b_reasons=b_reasons,
    )


def _stamp_and_persist(
    sc: Scorecard, result: GreenAuditResult, *, runs_dir: Optional[Path], out_dir: Optional[Path]
) -> None:
    """Write the sidecar (into the run dir) + stamp the scorecard evidence IN PLACE with the
    reserved keys only. The advisory invariant (verdict/attribution untouched) is enforced by
    the caller's snapshot/restore. Fail-soft — a persist miss never sinks the night."""
    pointer = ""
    if runs_dir and result.run_id:
        run_dir = Path(runs_dir) / result.run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / GREEN_QUALITY_SIDECAR_NAME).write_text(
                json.dumps(result.to_sidecar(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            pointer = f"state/fleet-runs/{result.run_id}/{GREEN_QUALITY_SIDECAR_NAME}"
        except OSError:
            pointer = ""
    evidence = dict(sc.evidence or {})
    evidence.update(result.evidence_stamp(pointer))
    sc.evidence = evidence


def audit_greens(
    scorecards: "list[Scorecard]",
    *,
    runs_dir: "str | Path | None" = None,
    out_dir: "str | Path | None" = None,
    projects_dir: "str | Path | None" = None,
    archive_root: "str | Path | None" = None,
    probe_dir: "str | Path | None" = None,
    job_surfaces: "dict[str, str] | None" = None,
    jurors: Optional[list[Juror]] = None,
    log: "Callable[[str], None] | None" = None,
) -> dict:
    """The battery-close entry point: audit every GREEN, write its ``green-quality.json``
    sidecar, stamp its scorecard evidence (advisory), and return the ``green_quality`` summary
    block for ``battery-summary.json``.

    Runs at battery close AFTER #832's per-job integrity gate (a GREEN #832 downgraded to
    PARKED is no longer GREEN, so it is correctly skipped here — integrity first, quality
    second) and before #827's ``classify``. NEVER raises (a fault leaves an empty block) and
    NEVER changes a
    verdict/attribution — snapshotted per card and restored + flagged on any mutation (the
    #827 advisory-lock pattern, mirrored)."""
    out_path = Path(out_dir) if out_dir else None
    surfaces = job_surfaces or {}
    results: list[GreenAuditResult] = []
    mode = MODE_DET_JURY if jurors else MODE_DET_ONLY

    for sc in scorecards:
        if sc.verdict != VERDICT_GREEN:
            continue
        before = (sc.verdict, sc.attribution)
        try:
            result = audit_green(
                sc, runs_dir=runs_dir, out_dir=out_dir, projects_dir=projects_dir,
                archive_root=archive_root, probe_dir=probe_dir,
                surface=surfaces.get(sc.job_id, ""), jurors=jurors,
            )
            if result is None:
                continue
            _stamp_and_persist(sc, result, runs_dir=Path(runs_dir) if runs_dir else None,
                               out_dir=out_path)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 — one GREEN's audit fault never sinks the night
            if log:
                log(f"[green-quality] {sc.job_id}: audit failed (fail-soft): {exc}")
            continue
        # The advisory invariant, enforced: the stamp touches evidence only. If a future edit
        # ever mutates verdict/attribution, restore it rather than let a mislabel bank.
        if (sc.verdict, sc.attribution) != before:
            sc.verdict, sc.attribution = before

    bands = {b: sum(1 for r in results if r.band == b) for b in BANDS}
    block = {
        "schema": GREEN_QUALITY_SCHEMA,
        "advisory": True,
        "audited": len(results),
        "mode": mode,
        "bands": bands,
        "regressed": sum(1 for r in results if r.layer1.regression.regressed),
        "craft_residue": sum(1 for r in results if r.layer1.any_craft_residue),
    }
    return block


def render_kpi(block: dict) -> list[str]:
    """The human KPI line for the battery-summary render (present only after the audit ran)."""
    if not block or not block.get("audited"):
        return []
    bands = block.get("bands") or {}
    parts = ", ".join(f"{b} {int(bands.get(b, 0) or 0)}" for b in BANDS)
    line = (f"green-quality ({block.get('mode', MODE_DET_ONLY)}): bands {parts}; "
            f"regressed={block.get('regressed', 0)}, craft-residue={block.get('craft_residue', 0)}")
    return [line + " [ADVISORY — never changes a verdict]"]
