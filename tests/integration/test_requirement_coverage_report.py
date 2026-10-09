"""Locks on `tools/probes/requirement_coverage_report.py`.

The property under lock is not "it joins two files". It is:

    **A requirement the operator stated must appear in the report even when the
    grader dropped it from its own denominator.**

`traceability.json` publishes `denominator_excludes` — typically `["build", "visual",
"human"]` — so on a job where he stated eight requirements the instrument grades six and
reports out of six. The two dropped ones are his sentences, and they vanish from every
figure the pipeline publishes. A coverage report that inherits that denominator would
tell him "6 of 6 considered" while two of his requirements were never looked at.

That is `docs/design/CODER_DEFINITION_OF_DONE.md`'s recurring defect — a denominator
excluding its own gaps — pointed at the operator rather than at a grader.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TOOL = (
    Path(__file__).resolve().parents[2] / "tools" / "probes" / "requirement_coverage_report.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("requirement_coverage_report", _TOOL)
    assert spec is not None and spec.loader is not None, f"cannot load {_TOOL}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["requirement_coverage_report"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rep():
    assert _TOOL.is_file(), (
        f"{_TOOL} is missing. If the probe moved, move this lock with it — the property "
        "is the point, not the path."
    )
    return _load()


def _mk(tmp_path: Path, *, spec_criteria, trace) -> Path:
    run = tmp_path / "fleet-runs" / "20260101-000000-bd"
    run.mkdir(parents=True)
    (run / "acceptance.json").write_text(
        json.dumps({"spec": {"goal": "g", "criteria": spec_criteria}}), encoding="utf-8"
    )
    if trace is not None:
        (run / "traceability.json").write_text(json.dumps(trace), encoding="utf-8")
    return run


def test_an_excluded_requirement_still_appears_in_his_own_words(rep, tmp_path):
    """THE lock. A tier the grader excludes is still a thing he asked for."""
    run = _mk(
        tmp_path,
        spec_criteria=[
            {"id": "c1", "tier": "behavior", "text": "the contact form should store enquiries"},
            {"id": "c2", "tier": "visual", "text": "every page should share one heading"},
        ],
        trace={
            "available": True,
            "denominator": 1,
            "denominator_excludes": ["visual"],
            "criteria": [{"id": "c1", "level": "L2-BOUND", "reason": ""}],
        },
    )
    out = rep.build_report(run)

    texts = [c["text"] for c in out["criteria"]]
    assert "every page should share one heading" in texts, (
        "a requirement the grader excluded vanished from the report. His sentence must "
        f"survive its exclusion; report carried {texts}"
    )
    excluded = [c for c in out["criteria"] if c["level"] == "NOT-IN-SCOPE"]
    assert len(excluded) == 1
    assert "visual" in excluded[0]["plain"], (
        "the excluded requirement does not say WHICH tier excluded it, so he cannot tell "
        "whether the exclusion was reasonable"
    )
    assert out["excluded_tiers"] == ["visual"]
    assert out["operator_requirement_count"] == 2, (
        "the report must count what HE stated, not what the grader graded — otherwise it "
        "reproduces the shrunken denominator it exists to expose"
    )


def test_undecidable_is_never_presented_as_coverage(rep, tmp_path):
    """UNDECIDABLE means the matcher could not tell. It is not a pass and not a fail."""
    run = _mk(
        tmp_path,
        spec_criteria=[{"id": "c1", "tier": "behavior", "text": "it should not crash"}],
        trace={
            "available": True,
            "denominator": 1,
            "denominator_excludes": [],
            "criteria": [
                {"id": "c1", "level": "UNDECIDABLE", "reason": "no oracle symbol matched"}
            ],
        },
    )
    out = rep.build_report(run)
    c = out["criteria"][0]
    assert c["level"] == "UNDECIDABLE"
    assert "cannot be determined" in c["plain"], (
        f"UNDECIDABLE was glossed as {c['plain']!r}; it must not read as checked or unchecked"
    )
    assert c["reason"], "an UNDECIDABLE verdict must carry the reason the matcher gave"


def test_a_run_with_no_measurement_says_so_rather_than_reporting_zero(rep, tmp_path):
    """'Nothing graded his requirements' and 'nothing covered them' are different facts."""
    run = _mk(
        tmp_path,
        spec_criteria=[{"id": "c1", "tier": "behavior", "text": "it should not crash"}],
        trace=None,
    )
    out = rep.build_report(run)
    assert out["available"] is False
    assert out["criteria"] == [], (
        "a run with no traceability.json produced criteria rows — the report invented "
        "coverage data for a measurement that never ran"
    )
    assert "never computed" in out["reason"] or "no traceability" in out["reason"]
    assert "NO COVERAGE MEASUREMENT" in rep.render(out)


def test_a_missing_acceptance_file_does_not_render_as_zero_requirements(rep, tmp_path):
    """The latent twin of this file's headline lock, found by a pre-merge reviewer.

    With `traceability.json` present and `acceptance.json` absent, an earlier version
    printed *"He stated 0 requirement(s). The exam graded 6 of them."* — a confident
    zero for a population that was never read, which is exactly what the sibling probe
    locks against and what this module did not.

    Latent today: 33 of 33 banked runs carry both files. Latent is not safe, and the
    fixture in every other test writes `acceptance.json`, so no existing test could
    reach it.
    """
    run = tmp_path / "fleet-runs" / "20260101-000000-bd"
    run.mkdir(parents=True)
    (run / "traceability.json").write_text(
        json.dumps(
            {
                "available": True,
                "denominator": 6,
                "denominator_excludes": [],
                "criteria": [{"id": "c1", "level": "L3-ASSERTED", "reason": ""}],
            }
        ),
        encoding="utf-8",
    )

    out = rep.build_report(run)
    assert out["operator_requirement_count"] == rep.ABSENT, (
        f"a missing acceptance.json rendered his requirement count as "
        f"{out['operator_requirement_count']!r}. 'He stated none' and 'we could not read "
        "what he stated' are different facts."
    )
    text = rep.render(out)
    assert "He stated 0 requirement" not in text
    assert "UNREADABLE" in text, (
        "the rendered report does not tell the reader his requirements could not be read"
    )


def test_the_plain_gloss_exists_for_every_level_the_pipeline_emits(rep):
    """He is non-technical. A level with no gloss is a report he cannot read."""
    for level in ("L0-GAP", "L1-DECLARED", "L2-BOUND", "L3-ASSERTED", "L4-KILLS", "UNDECIDABLE"):
        assert level in rep.LEVEL_PLAIN, f"no plain-language gloss for {level}"
        assert rep.LEVEL_PLAIN[level] != level
