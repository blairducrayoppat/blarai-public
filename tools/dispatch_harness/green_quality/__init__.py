"""#837 QUALITY-17 — the GREEN-quality audit (advisory, never verdict-changing).

The QUALITY companion to #832's earned-GREEN INTEGRITY audit (`green_audit.py`): #832 gates
grader-tampering (verdict-changing, GREEN→PARKED), this package reads the DISTINCT quality
axis (fragile / ugly / unusable) advisory-only, composing BENEATH #832's gate. At battery
close, for every job that still banks GREEN after the integrity gate, this package runs:

* **Layer 1** (:mod:`.layer1`) — the deterministic floor: the archetype-regression probe
  (diff the GREEN's observable behaviour against the last archived GREEN of the same card),
  craft lints (dead scaffold / stale README / no runnable entry point), the seed-divergence
  check (is a delivered file still the file it was copied from?), and advisory ruff.
  This layer alone would have caught the B2 tokenizer regression the flat GREEN scoreboard
  missed. No model, seconds, ecosystem-agnostic where it can be.
* **The security scan** (:mod:`.security`, #1182) — the deterministic SECURITY floor, a
  Layer-1-class check in its own module: credential material in source, code and queries
  built out of strings, and unescaped markup reaching a browser. It closes the gap where the
  coder was never told to write secure code, never asked for it by a card, and never graded
  on whether it did — so a web deliverable with an injection hole banked GREEN band A. It is
  the one deterministic check that forces band C alone, and the one whose SILENCE is itself a
  caveat: an unmeasured scan is never rendered as clean.
* **The placeholder-prose scan** (:mod:`.placeholder_prose`, #1281) — the deterministic
  CONTENT floor over the delivered pages. A website is mostly words, and nothing in the
  intake, the plan or the exams asked for any of them, so a site that shipped lorem ipsum or
  "Welcome to My Site" banded A. It grades one thing only: whether text that announces itself
  as unfinished survived into a delivered page. Whether the writing is any GOOD is the
  operator's judgment (#1280) and is not modelled here. Deliberately the quietest input to
  the band — an unambiguous finding is a B caveat, never a C, and its MEDIUM tier never moves
  a letter at all.
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
from . import placeholder_prose as _prose
from . import security as _security
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
    EV_PROSE,
    EV_REGRESSED,
    EV_RUNNABLE,
    EV_SECURITY,
    EV_SEED_IDENTICAL,
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
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
)

# Re-exports (the package's public surface).
from .band import compute_band  # noqa: E402,F401
from .calibration import CalibrationPair, agreement_rate, record_pair  # noqa: E402,F401
from .card import WhatYouGotCard, build_card  # noqa: E402,F401
from .jury import Juror, JuryResult, build_default_jury, run_jury  # noqa: E402,F401
from .layer1 import (  # noqa: E402,F401
    Layer1Result,
    ProbeSet,
    SeedDivergenceFinding,
    audit_layer1,
    default_seed_root,
    find_reference_green,
    lint_seed_divergence,
    load_probe_set,
)
from .placeholder_prose import (  # noqa: E402,F401
    DISPOSITION_CLEAN,
    DISPOSITION_NOT_APPLICABLE,
    DISPOSITION_PLACEHOLDER,
    DISPOSITION_UNMEASURED,
    ProseFinding,
    ProseResult,
)
from .security import SecurityFinding, SecurityResult, scan_repo  # noqa: E402,F401

#: The security scan's signature as :func:`audit_green` injects it (repo, surface) -> result.
SecurityScanner = Callable[[Optional[Path], str], SecurityResult]
#: The placeholder-prose scan's signature, injected on the same pattern (repo, surface) -> result.
ProseScanner = Callable[[Optional[Path], str], ProseResult]

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
    #: The #1182 deterministic security scan. Never ``None`` in a real audit — a scan that
    #: could not run is a result carrying ``measured=False``, so the absence of findings can
    #: always be told apart from the absence of a look.
    security: SecurityResult = field(default_factory=SecurityResult)
    #: The #1281 placeholder-prose scan. Never ``None`` in a real audit, on the same
    #: reasoning as ``security`` above — and carrying one state that check does not: a tree
    #: with no user-visible prose in it (a library) is NOT APPLICABLE, which is a different
    #: statement from clean and must never borrow its word.
    prose: ProseResult = field(default_factory=ProseResult)
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
                # Each craft flag is persisted WITH its measured bit, on the same reasoning as
                # `regression_measured` above. A `measured` field consulted only at RENDER time
                # leaves the ARCHIVE mute: #1198's author found that instrument's own 36-day
                # history could not say, per report, whether the tool was missing or merely had
                # nothing to examine, because the record kept the finding and discarded the fact
                # of looking. An instrument has to RECORD that it measured, not merely be
                # willing to answer when asked.
                "dead_scaffold": self.layer1.dead_scaffold.flagged,
                "dead_scaffold_measured": self.layer1.dead_scaffold.measured,
                "stale_readme": self.layer1.stale_readme.flagged,
                "stale_readme_measured": self.layer1.stale_readme.measured,
                "no_entry_point": self.layer1.no_entry_point.flagged,
                "no_entry_point_measured": self.layer1.no_entry_point.measured,
                # A STATUS STRING, never a bool: "unknown" (the seed could not be read) must be
                # impossible to mistake for "clean" by any later reader of this file. The
                # per-file lists below carry which files landed in which state.
                "seed_divergence": self.layer1.seed_divergence.status,
                "seed_identical_files": list(self.layer1.seed_divergence.identical),
                "seed_unchecked_files": list(self.layer1.seed_divergence.unknown),
                "seed_root": self.layer1.seed_divergence.seed_root,
                "ruff_findings": self.layer1.ruff_findings,
            },
            "layer1_findings": [_clip(f) for f in self.layer1.findings()],
            "security": {
                # measured=False is the honest "could not determine" — a reader must never
                # infer clean from an empty findings list without checking this flag.
                "measured": self.security.measured,
                "status": _clip(self.security.status),
                "files_scanned": self.security.files_scanned,
                "worst_severity": self.security.worst_severity,
                "clean": self.security.is_clean(),
                "findings": [
                    {"rule": f.rule, "severity": f.severity, "path": f.path,
                     "line": f.line, "detail": _clip(f.detail)}
                    for f in self.security.findings
                ],
            },
            "prose": {
                # FOUR-WAY, and the disposition is written FIRST because it is the only field
                # here that cannot be misread: `measured` and `applicable` are two booleans a
                # later reader will combine wrongly, while "not-applicable" cannot be mistaken
                # for "clean" by anyone. The two booleans are persisted alongside it so the
                # archive can still answer questions the disposition collapses.
                "disposition": self.prose.disposition(),
                "measured": self.prose.measured,
                "applicable": self.prose.applicable,
                "status": _clip(self.prose.status),
                "pages_scanned": self.prose.pages_scanned,
                "worst_severity": self.prose.worst_severity,
                "findings": [
                    # `means` carries the plain-language sentence for EVERY finding, not only
                    # the HIGH ones the band and the card render. The sidecar is the artifact
                    # a later reader (or the operator, over someone's shoulder) opens to ask
                    # what a rule id meant, and a rule whose sentence exists but is reachable
                    # from nothing is a string nobody can get to.
                    {"rule": f.rule, "severity": f.severity, "path": f.path,
                     "line": f.line, "detail": _clip(f.detail), "means": f.means()}
                    for f in self.prose.findings
                ],
            },
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
        ONLY these keys are ever written — never a verdict/attribution.

        NO KEY HERE IS FLAG-SHAPED, and that is the whole point of this docstring. A key
        written only when its check FIRED makes an absent key mean two opposite things: the
        check looked and found nothing, or the check never looked. The security stamp was
        given an honest shape for exactly that reason (the comment below states it) and the
        three layer-1 keys were left flag-shaped, so an unmeasured regression probe,
        dead-scaffold lint or seed comparison stamped a scorecard that read identically to a
        clean one. Each of the three now answers three ways:

        * measured + fired  -> the key carries the finding;
        * NOT measured      -> the key carries this instrument's registered disclosure
          marker, so silence is never how "did not look" is expressed;
        * measured + clean  -> the key is absent, which is only now unambiguous.

        Security keeps its own arrangement — always present, three-way in its VALUE — because
        the absence of a security key is the one absence that must never be reachable at all.
        The disclosure strings are the markers registered in
        :mod:`shared.instrument_registry`; a reader, or a downstream consumer, tells a
        disclosure from a finding by the marker, never by presence."""
        stamp: dict = {
            EV_BAND: self.band,
            EV_MODE: self.mode,
            EV_CARD: self.card.to_evidence(),
            EV_FINDINGS: sidecar_pointer,
            # UNCONDITIONAL: the security stamp reads "clean (N files)" /
            # "could-not-determine: …" / the findings. A key present only on a finding would
            # make silence ambiguous, and silence is exactly what this scan must never be
            # allowed to mean "safe".
            EV_SECURITY: self.security.summary(),
            # UNCONDITIONAL for the same reason, and four-way rather than three: the stamp
            # reads "could-not-determine: …" / "not-applicable: …" / "no placeholder prose
            # (N pages read)" / the findings. A deliverable with no pages in it must not stamp
            # the same string as a site whose pages were read and were fine.
            EV_PROSE: self.prose.summary(),
        }
        reg = self.layer1.regression
        if not reg.measured:
            stamp[EV_REGRESSED] = _clip(f"regression probe NOT RUN — {reg.detail} "
                                        f"(absent measurement, not a clean one)")
        elif reg.regressed:
            stamp[EV_REGRESSED] = _clip(reg.detail)
        dead_scaffold = self.layer1.dead_scaffold
        if not dead_scaffold.measured:
            stamp[EV_DEAD_SCAFFOLD] = _clip(f"dead scaffold lint NOT RUN — {dead_scaffold.detail} "
                                            f"(absent measurement, not a clean one)")
        elif dead_scaffold.flagged:
            stamp[EV_DEAD_SCAFFOLD] = "residue"
        seed = self.layer1.seed_divergence
        if not seed.measured:
            stamp[EV_SEED_IDENTICAL] = _clip(f"seed divergence UNKNOWN — {seed.detail}")
        elif seed.flagged:
            stamp[EV_SEED_IDENTICAL] = ",".join(seed.identical)
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
    seed_root: "str | Path | None" = None,
    surface: str = "",
    jurors: Optional[list[Juror]] = None,
    security_scan: "SecurityScanner" = _security.scan_repo,
    prose_scan: "ProseScanner" = _prose.scan_repo,
    prose_band: Optional[bool] = None,
) -> Optional[GreenAuditResult]:
    """Audit ONE GREEN scorecard, or ``None`` if it is not a GREEN. Pure of side effects on
    the scorecard (stamping is :func:`audit_greens`'s job); returns the full result so a
    caller can stamp, write the sidecar, and render the card.

    ``security_scan`` and ``prose_scan`` are injected on the same pattern as Layer 1's
    ``run``/``ruff``, so a test can substitute a disabled scanner and prove that a caught
    defect is attributable to THIS control rather than to some other check that happened to
    fire.

    ``prose_band`` is THE CONSEQUENCE GATE for #1281's scan, and this function is the single
    seam that spends it: ``None`` asks :func:`~.placeholder_prose.prose_band_enabled` (which
    reads ``[fleet_dispatch].green_quality_prose_band`` — the config is the authority, never
    this docstring), and an explicit bool lets a caller decide. When it is not granted the
    prose result is withheld from :func:`~.band.band_reasons` and :func:`~.card.build_card`
    ENTIRELY, which is dormancy by structural absence rather than by a branch inside the
    formula: the pure band function stays pure, keeps its own contract that ``prose=None``
    carries no signal, and there is exactly one place a mistake could grant this. The result
    itself is untouched — the sidecar, the evidence stamp and the rollup counts are the
    MEASUREMENT and they are never gated."""
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
        reference_repo, probe_set, surface=surf, seed_root=seed_root,
    )

    # The security scan reads the SAME resolved tree Layer 1 lints. Guarded here as well as
    # inside the scanner: a scanner that raises must degrade to "could not determine", never
    # to a missing result that a downstream reader could mistake for a clean one.
    try:
        sec = security_scan(current_repo, surf)
    except Exception as exc:  # noqa: BLE001 - fail-soft, but never fail-open
        sec = _security.SecurityResult(
            status=f"security scan raised {type(exc).__name__} (treated as not measured)")

    # Same tree, same guard, same reason: a scanner that raises degrades to "could not
    # determine", never to a missing result a downstream reader could mistake for clean.
    try:
        prose = prose_scan(current_repo, surf)
    except Exception as exc:  # noqa: BLE001 - fail-soft, but never fail-open
        prose = _prose.ProseResult(
            status=f"placeholder-prose scan raised {type(exc).__name__} "
                   f"(treated as not measured)")

    jury_result: Optional[JuryResult] = None
    mode = MODE_DET_ONLY
    if jurors:
        jury_result = run_jury(jurors, _jury_subject(current_repo, l1))
        mode = MODE_DET_JURY

    # The consequence gate (#1281). `graded` is the prose result ONLY when the band contribution
    # has been granted; otherwise the band and the card never see it at all. `prose` below is
    # the full result regardless — measurement and consequence travel separately by design.
    graded = prose if (_prose.prose_band_enabled() if prose_band is None else prose_band) else None
    chosen_band, c_reasons, b_reasons = _band.band_reasons(l1, jury_result, sec, graded)
    the_card = build_card(sc.job_id, surf, chosen_band, l1,
                          jury_uncertain=jury_result.uncertain if jury_result else None,
                          security=sec, prose=graded)

    return GreenAuditResult(
        job_id=sc.job_id, run_id=sc.run_id, repo=repo_slug, surface=surf,
        band=chosen_band, mode=mode, layer1=l1, jury=jury_result, card=the_card,
        reference_green=str(reference_repo) if reference_repo else None,
        security=sec, prose=prose, c_reasons=c_reasons, b_reasons=b_reasons,
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
    seed_root: "str | Path | None" = None,
    job_surfaces: "dict[str, str] | None" = None,
    jurors: Optional[list[Juror]] = None,
    security_scan: "SecurityScanner" = _security.scan_repo,
    prose_scan: "ProseScanner" = _prose.scan_repo,
    prose_band: Optional[bool] = None,
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
    #827 advisory-lock pattern, mirrored).

    ``prose_band`` is resolved ONCE here and threaded into every card's audit, rather than
    re-read per GREEN: the config does not change during a battery close, and one night must
    not be able to grade its first deliverable under a different posture from its last."""
    out_path = Path(out_dir) if out_dir else None
    surfaces = job_surfaces or {}
    results: list[GreenAuditResult] = []
    #: job_ids whose audit RAISED. Not a log line -- a durable count that reaches the
    #: operator's rollup, because the log is not what he reads (#1270).
    audit_failed: list[str] = []
    mode = MODE_DET_JURY if jurors else MODE_DET_ONLY
    band_prose = _prose.prose_band_enabled() if prose_band is None else prose_band

    for sc in scorecards:
        if sc.verdict != VERDICT_GREEN:
            continue
        before = (sc.verdict, sc.attribution)
        try:
            result = audit_green(
                sc, runs_dir=runs_dir, out_dir=out_dir, projects_dir=projects_dir,
                archive_root=archive_root, probe_dir=probe_dir, seed_root=seed_root,
                surface=surfaces.get(sc.job_id, ""), jurors=jurors,
                security_scan=security_scan, prose_scan=prose_scan, prose_band=band_prose,
            )
            if result is None:
                continue
            _stamp_and_persist(sc, result, runs_dir=Path(runs_dir) if runs_dir else None,
                               out_dir=out_path)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - one GREEN's audit fault never sinks the night
            if log:
                log(f"[green-quality] {sc.job_id}: audit failed (fail-soft): {exc}")
            # COUNTED IN THE SAME STATEMENT THAT DROPS IT (#1270). Fail-soft is right — one
            # GREEN's fault must not sink the night — but a card that vanished from `results`
            # was previously counted NOWHERE: not as audited, not as unmeasured, not at all.
            # `audited: len(results)` then described a smaller night as a complete one, which
            # is the exact thing corpus_block's own docstring refuses ("a count without its
            # unmeasured partner is not a smaller report, it is a wrong one").
            audit_failed.append(sc.job_id)
            continue
        # The advisory invariant, enforced: the stamp touches evidence only. If a future edit
        # ever mutates verdict/attribution, restore it rather than let a mislabel bank.
        if (sc.verdict, sc.attribution) != before:
            sc.verdict, sc.attribution = before

    return corpus_block(results, mode, audit_failed=tuple(audit_failed))


def corpus_block(
    results: list[GreenAuditResult], mode: str, *, audit_failed: tuple[str, ...] = (),
) -> dict:
    """The ``green_quality`` summary block for ``battery-summary.json`` — the night's rollup.

    Extracted from :func:`audit_greens` so it is a NAMED renderer the instrument sweep can
    resolve, and so the counters can be driven directly. It renders to the battery summary and
    from there to the operator's KPI line, which makes it an instrument renderer in the
    registry's sense: its output is read as fact.

    EVERY count here is PAIRED with its unmeasured count. The security block was already
    written that way; ``regressed`` and ``craft_residue`` were not, so a night on which the
    probe never ran and a night on which it ran clean produced the same ``regressed=0`` — the
    fail-open this rollup exists to refuse, in the one artifact the operator reads at a glance.
    A count without its unmeasured partner is not a smaller report, it is a wrong one."""
    bands = {b: sum(1 for r in results if r.band == b) for b in BANDS}
    return {
        "schema": GREEN_QUALITY_SCHEMA,
        "advisory": True,
        "audited": len(results),
        # The cards that RAISED. `audited` alone described a partial night as a whole
        # one; these two are only meaningful together (#1270).
        "audit_failed": len(audit_failed),
        "audit_failed_jobs": list(audit_failed),
        "mode": mode,
        "bands": bands,
        "regressed": sum(1 for r in results
                         if r.layer1.regression.measured and r.layer1.regression.regressed),
        "regression_unmeasured": sum(1 for r in results if not r.layer1.regression.measured),
        # `any_craft_residue` is already per-lint guarded; the blind lints are counted here
        # rather than folded into it, because a bool cannot carry the third state.
        "craft_residue": sum(1 for r in results if r.layer1.any_craft_residue),
        "craft_unmeasured": sum(1 for r in results if r.layer1.craft_lints_unmeasured),
        # Three separate counters, deliberately: a GREEN with a HIGH finding, one with only a
        # caveat-grade finding, and one nobody could scan are three different states, and
        # collapsing the third into "clean" is the fail-open this instrument exists to refuse.
        "security_high": sum(1 for r in results if r.security.at_or_above(SEVERITY_HIGH)),
        "security_caveat": sum(
            1 for r in results
            if not r.security.at_or_above(SEVERITY_HIGH) and r.security.at_or_above(SEVERITY_MEDIUM)
        ),
        "security_unmeasured": sum(1 for r in results if not r.security.measured),
        # FOUR counters for four states, and the fourth is the one worth defending:
        # `prose_not_applicable` counts deliverables with no user-visible prose at all (a
        # library, a command-line tool). Folding those into `prose_clean` would let a night of
        # nothing but libraries render as a night of well-written sites, and folding them into
        # `prose_unmeasured` would raise an alarm about a deliverable that is behaving exactly
        # as it should. Every count is read off `disposition()` rather than off the booleans,
        # so no caller here can recombine them wrongly.
        "prose_placeholder": sum(
            1 for r in results if r.prose.disposition() == DISPOSITION_PLACEHOLDER),
        "prose_clean": sum(1 for r in results if r.prose.disposition() == DISPOSITION_CLEAN),
        "prose_not_applicable": sum(
            1 for r in results if r.prose.disposition() == DISPOSITION_NOT_APPLICABLE),
        "prose_unmeasured": sum(
            1 for r in results if r.prose.disposition() == DISPOSITION_UNMEASURED),
    }


def render_kpi(block: dict) -> list[str]:
    """The human KPI line for the battery-summary render (present only after the audit ran).

    Every count is rendered WITH its not-measured partner, at zero as much as at ten. A KPI
    line is skimmed, so an omitted zero is read as "nothing to report" rather than as "not
    asked" — which is the same collapse one rendering layer further out."""
    if not block:
        return []
    failed = int(block.get("audit_failed", 0) or 0)
    if not block.get("audited"):
        # THE COLLAPSE THIS FUNCTION EXISTS TO REFUSE, one layer out (#1270). Returning []
        # here made a night whose every audit RAISED render byte-identically to a night with
        # no GREENs at all — the most reassuring output this function can emit, produced by
        # its worst input. `audited == 0` is only silence-worthy when nothing failed either.
        if failed:
            return [
                f"green-quality: NOT MEASURED — all {failed} GREEN(s) failed to audit "
                f"({', '.join(block.get('audit_failed_jobs') or []) or 'jobs unrecorded'})"
                " [ADVISORY - never changes a verdict]",
                "  no quality signal was produced for this night",
            ]
        return []
    bands = block.get("bands") or {}
    parts = ", ".join(f"{b} {int(bands.get(b, 0) or 0)}" for b in BANDS)
    line = (f"green-quality ({block.get('mode', MODE_DET_ONLY)}): bands {parts}; "
            f"regressed={block.get('regressed', 0)} "
            f"(not-measured={block.get('regression_unmeasured', 0)}), "
            f"craft-residue={block.get('craft_residue', 0)} "
            f"(not-measured={block.get('craft_unmeasured', 0)})")
    # The unmeasured count is rendered even at zero: a reader scanning the night's KPI must be
    # able to see that the security scan ran, not merely that it reported nothing.
    security = (f"security: high={block.get('security_high', 0)}, "
                f"caveat={block.get('security_caveat', 0)}, "
                f"not-measured={block.get('security_unmeasured', 0)}")
    # The partial case: some cards audited, some raised. Rendered beside the counts rather
    # than instead of them, because `audited=2` on a five-GREEN night is not wrong about the
    # two — it is silent about the three (#1270).
    if failed:
        line += f"; audit-failed={failed}"
    # Rendered at zero on the same principle as the security line, and with the no-prose-
    # surface count kept VISIBLE rather than folded away: "placeholder=0" on a night of five
    # libraries means something very different from "placeholder=0" on a night of five sites,
    # and the operator reading one KPI line cannot tell them apart without this number.
    prose = (f"prose: placeholder={block.get('prose_placeholder', 0)}, "
             f"clean={block.get('prose_clean', 0)}, "
             f"no-prose-surface={block.get('prose_not_applicable', 0)}, "
             f"not-measured={block.get('prose_unmeasured', 0)}")
    return [line + " [ADVISORY - never changes a verdict]", "  " + security, "  " + prose]
