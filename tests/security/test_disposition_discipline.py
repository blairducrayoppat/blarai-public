"""Gate lock for the finding-disposition control (2026-07-20).

WHAT FAILURE THIS EXISTS FOR
----------------------------
On 2026-07-20 an independent review returned three findings. Two of them needed
no decision at all, and I filed them as tickets instead of fixing them - then
reported to the Lead Architect that the surfaces were handled. They were not.
The reason was not a judgement call: the change had already merged and the box
felt closed. **Momentum, not judgement.**

Doctrine already forbade exactly this, in two places (``decision_boundary``:
*"Reporting a defect without fixing it = incomplete response"*, and the
standing directive *"Before deferring, name the concrete failure the delay
prevents; 'it feels safer' is not a reason"*). Restating a rule that was
written and ignored buys nothing. This is the structural control instead, per
the curation rule that a recurring failure must ship one.

WHAT IS LOCKED HERE
-------------------
1. Every disposition record in the repo stays well-formed forever (rot guard).
2. Every FIXED row's commit-ish evidence actually RESOLVES in this repo - the
   verifier alone can only check shape, and a plausible-but-wrong SHA is the
   precise shape of the errors this whole control answers.
3. The verifier genuinely REFUSES each failure mode. Every check below has a
   planted-violation twin, because a validator nobody has watched reject
   something is not known to work (security_by_design principle 12).

The toggle-off proofs matter more than the positive cases here. The filler-
phrase blocklist is the teeth of the control: it is what would have caught the
2026-07-20 deferrals, because "follow-up" is what I would have written.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify_disposition.py"
REVIEW_DIR = REPO_ROOT / "docs" / "reviews"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from verify_disposition import check_row, extract_block, verify  # noqa: E402

SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

GOOD = """```disposition
ADR-012 inverted draft claim | FIXED | f4211acc, merged e1cf0d68
runbook self-contradiction   | DEFERRED | #990 blocked-by: needs the `gov-pf-007` re-baseline in `evals/golden/governance.jsonl` verified first
image_generation shim wording | REJECTED | verified accurate against tools.py line 31; the directive shim genuinely has nothing to gate
```"""


def _rows(md: str):
    rows, err = extract_block(md)
    assert err is None, err
    return rows


def _run(md: str, tmp_path: Path) -> tuple[int, str]:
    f = tmp_path / "disposition.md"
    f.write_text(md, encoding="utf-8")
    code, report = verify(f)
    return code, "\n".join(report)


# --------------------------------------------------------------------------
# 1. Positive control
# --------------------------------------------------------------------------

def test_a_well_formed_disposition_passes(tmp_path: Path) -> None:
    code, report = _run(GOOD, tmp_path)
    assert code == 0, report


# --------------------------------------------------------------------------
# 2. Toggle-off proofs - one per failure mode. These ARE the control.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "predicate",
    [
        "follow-up",
        "a follow up",
        "lower priority",
        "not a high priority",
        "it feels safer to wait",
        "next session",
        "when time permits",
        "out of scope for now",
        "nice to have",
        "can wait",
        "once things settle",
    ],
)
def test_filler_predicates_are_refused(predicate: str, tmp_path: Path) -> None:
    """The teeth. Every one of these reads like a reason and decides nothing."""
    md = f"```disposition\nsome finding | DEFERRED | #123 blocked-by: {predicate}\n```"
    code, report = _run(md, tmp_path)
    assert code != 0, f"filler predicate {predicate!r} was ACCEPTED:\n{report}"
    assert "filler phrase" in report or "nothing observable" in report, report


def test_deferral_without_an_observable_predicate_is_refused(tmp_path: Path) -> None:
    md = "```disposition\nx | DEFERRED | #123 blocked-by: waiting for the design to be clearer\n```"
    code, report = _run(md, tmp_path)
    assert code != 0 and "nothing observable" in report, report


def test_deferral_without_a_ticket_is_refused(tmp_path: Path) -> None:
    """A deferral outside the durable queue is a dropped finding."""
    md = "```disposition\nx | DEFERRED | blocked-by: `default.toml` must flip first\n```"
    code, report = _run(md, tmp_path)
    assert code != 0 and "no #ticket" in report, report


def test_deferral_without_a_blocked_by_clause_is_refused(tmp_path: Path) -> None:
    md = "```disposition\nx | DEFERRED | #123 will look at it later\n```"
    code, report = _run(md, tmp_path)
    assert code != 0 and "blocked-by" in report, report


def test_fixed_without_commitish_evidence_is_refused(tmp_path: Path) -> None:
    """'Fixed' is a claim; a claim without an artifact is the whole defect class."""
    md = "```disposition\nx | FIXED | dealt with it\n```"
    code, report = _run(md, tmp_path)
    assert code != 0 and "commit-ish" in report, report


def test_rejected_without_argument_is_refused(tmp_path: Path) -> None:
    md = "```disposition\nx | REJECTED | not a defect\n```"
    code, report = _run(md, tmp_path)
    assert code != 0 and "word(s) of reason" in report, report


def test_absent_block_is_refused_deny_by_default(tmp_path: Path) -> None:
    """Silence is the failure mode, so an absent block can never pass."""
    code, report = _run("# A review with prose but no machine-checkable block\n", tmp_path)
    assert code != 0 and "deny-by-default" in report, report


def test_empty_block_is_refused(tmp_path: Path) -> None:
    code, report = _run("```disposition\n```", tmp_path)
    assert code != 0 and "empty" in report, report


def test_placeholder_evidence_is_refused(tmp_path: Path) -> None:
    md = "```disposition\nx | FIXED | <sha>\n```"
    code, report = _run(md, tmp_path)
    assert code != 0 and "placeholder" in report, report


def test_unknown_status_is_refused(tmp_path: Path) -> None:
    md = "```disposition\nx | PARTIALLY | #123 blocked-by: #990\n```"
    code, report = _run(md, tmp_path)
    assert code != 0 and "unknown status" in report, report


# --------------------------------------------------------------------------
# 3. The blocklist must not be so broad it punishes honest predicates
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "predicate",
    [
        "#989 must be decided first - the fix depends on the chosen job grain",
        "blocked until `tools/qwen_toolcall_fix.py` accepts both separators (#991)",
        "the 2026-07-30 genai PR #4139 check-back",
        "`evals/golden/governance.jsonl` must be re-baselined in the same change",
    ],
)
def test_honest_predicates_are_accepted(predicate: str, tmp_path: Path) -> None:
    """A control that punishes the honest form pushes people to game it.

    This is the lesson from the #978 gate, which flagged security_by_design
    principle 2 - a true, timeless statement - and would have had us weaken the
    doctrine to satisfy a regex. Both directions are pinned here so neither
    can drift.
    """
    md = f"```disposition\nx | DEFERRED | #123 blocked-by: {predicate}\n```"
    code, report = _run(md, tmp_path)
    assert code == 0, f"honest predicate {predicate!r} was REFUSED:\n{report}"


# --------------------------------------------------------------------------
# 4. Real records in the repo: well-formed, and their SHAs actually resolve
# --------------------------------------------------------------------------

# A real disposition block opens a fence at the START of a line. A bare substring search also
# matches a document that merely DISCUSSES the convention — an inline `` ```disposition `` in
# prose — and then demands that the discussion be a valid record. Found 2026-07-22: an
# independent review whose text explained the disposition requirement to the author was itself
# selected as a malformed disposition record and failed the standing gate.
#
# Anchoring to line start is strictly more correct, not a loosening: `verify_disposition.py`'s
# own BLOCK_RE only ever matches a fence it can parse a body out of, so a file this selector
# now skips could never have produced a valid record anyway.
_BLOCK_FENCE = re.compile(r"^```disposition\s*$", re.M)


def _disposition_files() -> list[Path]:
    if not REVIEW_DIR.is_dir():
        return []
    return sorted(
        p for p in REVIEW_DIR.glob("*.md")
        if _BLOCK_FENCE.search(p.read_text(encoding="utf-8"))
    )


def test_every_recorded_disposition_stays_well_formed() -> None:
    """Rot guard: a record that was honest when written must stay honest."""
    for path in _disposition_files():
        code, report = verify(path)
        assert code == 0, f"{path.name} no longer verifies:\n{report}"


def test_fixed_rows_cite_shas_that_actually_resolve() -> None:
    """The check the verifier cannot make alone.

    A structurally valid but non-existent SHA is exactly the shape of the
    2026-07-20 errors: a claim that looks like evidence and was never checked
    against the thing itself.
    """
    for path in _disposition_files():
        for row in _rows(path.read_text(encoding="utf-8")):
            if row.status != "FIXED":
                continue
            for sha in SHA_RE.findall(row.evidence):
                out = subprocess.run(
                    ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                    cwd=REPO_ROOT, capture_output=True,
                )
                assert out.returncode == 0, (
                    f"{path.name}: row {row.finding!r} cites SHA {sha} which does not resolve "
                    f"in this repo - evidence that cannot be checked is not evidence"
                )


def test_the_verifier_is_wired_and_executable() -> None:
    """Reachability, not just behaviour - the built-but-wired-into-nothing guard."""
    assert VERIFIER.exists(), f"missing {VERIFIER}"
    out = subprocess.run([sys.executable, str(VERIFIER), "--help"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
