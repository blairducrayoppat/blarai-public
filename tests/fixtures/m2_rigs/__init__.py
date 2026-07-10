"""M2 adversarial rig fixtures (plan §9.3 / §10.2) — reusable data + loaders.

Each fixture is a data file (or small file tree) whose docstring / ``surface``
field names the §10 threat surface it attacks. The rigs are consumed by
``shared/tests/test_m2_rigs.py`` today (structural assertions against the
reference stubs) and, as W1-W5 land, by the L1 simulator + the live battery
(the B8 negative carrier). One import surface so a test never hard-codes a path.
"""

from __future__ import annotations

import json
from pathlib import Path

RIGS_DIR = Path(__file__).resolve().parent


def rig_path(*parts: str) -> Path:
    """Absolute path to a fixture under ``tests/fixtures/m2_rigs``."""
    return RIGS_DIR.joinpath(*parts)


def load_json(*parts: str) -> dict:
    """Read a JSON fixture. Raises on malformed JSON (a broken rig is loud)."""
    return json.loads(rig_path(*parts).read_text(encoding="utf-8"))


def read_text(*parts: str) -> str:
    """Read a text/source fixture verbatim."""
    return rig_path(*parts).read_text(encoding="utf-8")
