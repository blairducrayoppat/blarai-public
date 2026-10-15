"""Lock: ADR-045 quotes the external proposal's fallback sentence word for word (#1777).

The quotation is checked against the repository's own record of the raw read (workstream-0 notes), so a paraphrase put inside
quotation marks, or a record edited to match one, fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = next((ROOT / "docs" / "adrs").glob("ADR-045-*.md"))
RECORD = ROOT / "docs" / "research" / "windows-containment-comparison-2026-10" / "workstream-0" / "ws0-nono-srt.md"
QUOTED = ('documented fallback only \u2014 used where AppContainer cannot express a specific confinement need '
          '(handle isolation, job limits) with acceptable robustness, and only for that need, not as the default posture')


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", ""))


def test_the_adr_quotes_the_proposals_fallback_sentence_verbatim() -> None:
    assert f'"{QUOTED}"' in _plain(ADR.read_text(encoding="utf-8"))


def test_the_quoted_sentence_is_in_the_record_of_the_raw_read() -> None:
    assert QUOTED in _plain(RECORD.read_text(encoding="utf-8"))


def test_toggle_a_paraphrase_inside_quotation_marks_is_not_the_quotation() -> None:
    assert '"needs AppContainer cannot meet"' not in _plain(ADR.read_text(encoding="utf-8"))
    assert f'"{QUOTED}"' not in _plain('as "documented fallback" for "needs AppContainer cannot meet"')
