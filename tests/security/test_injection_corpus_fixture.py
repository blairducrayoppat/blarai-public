"""Fixture-integrity lock for the promptfoo injection corpus (#1004).

The corpus at ``evals/fixtures/injection_corpus/promptfoo_injection_corpus.json``
is static red-team INPUT data — prompt-injection technique strings extracted
verbatim from promptfoo (MIT), for adversarial use against the Policy Agent.
This test is the control that keeps the fixture honest. It is fully
deterministic: no model, no network, no runtime import of the fixture.

What it locks:

1. **No silent corpus loss.** ``counts`` are pinned constants and must equal
   the real number of templates; the placeholder split is pinned too. A future
   edit that drops or adds an entry fails loud.
2. **No silent content drift.** ``content_sha256`` is a pin over every template
   in source order; the test recomputes it from the loaded templates and
   compares. Any edit to any template — or a reorder — fails loud.
3. **Provenance travels.** The top-level provenance block must name the pinned
   upstream repo, path, commit, and blob sha, and declare MIT. (The corpus was
   consolidated to ONE provenance block referenced by each entry's
   ``source_index`` rather than repeating the commit sha on all 106 rows —
   this test proves the block is present and pinned.)
4. **Both required notices ship.** ``LICENSE.promptfoo`` (promptfoo MIT) and
   ``NOTICE.md`` (the Protect AI / llm-guard MIT notice at the pinned llm-guard
   commit) exist and carry their required phrases. MIT requires the notices
   travel with redistributed material.
5. **Per-entry shape.** Every entry has a unique id, a ``source_index`` equal
   to its position, a known technique tag, and ``has_placeholder`` /
   ``placeholder_count`` consistent with the actual template text.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = _REPO / "evals" / "fixtures" / "injection_corpus"
_CORPUS = _FIXTURE_DIR / "promptfoo_injection_corpus.json"
_LICENSE = _FIXTURE_DIR / "LICENSE.promptfoo"
_NOTICE = _FIXTURE_DIR / "NOTICE.md"

# --- Pinned constants (silent-loss / silent-drift tripwires) ---------------
_PIN_TOTAL = 106
_PIN_WITH_PLACEHOLDER = 74
_PIN_WITHOUT_PLACEHOLDER = 32
_PIN_CONTENT_SHA256 = "67d8609c00c4105f625319ef71f8d8389d62c2c4df54b51859a5973e83b41560"
_PIN_SOURCE_COMMIT = "e8fc168b60eb73702f4ab543f694d5a230e7cd7f"
_PIN_SOURCE_BLOB_SHA = "b3e8383667ee3fbe2dd14248d354c75b7a6ef82f"
_PIN_SOURCE_PATH = "src/redteam/strategies/promptInjections/data.ts"
_PIN_LLMGUARD_COMMIT = "399cb2eea70afc78482db226253ddd1d85f296e3"

_PLACEHOLDER = "__PROMPT__"

# Technique tags are a LOCAL heuristic (see the fixture README). The enum is
# pinned so a typo or a silently-introduced new bucket fails loud; the per-tag
# COUNTS are deliberately NOT pinned (they are display, not contract).
_KNOWN_TECHNIQUES = {
    "skeleton-key",
    "code-execution-sim",
    "developer-mode",
    "dan",
    "dude",
    "stan",
    "aim",
    "mode-jailbreak",
    "hypothetical-framing",
    "entity-splitting",
    "dual-response",
    "persona-roleplay",
    "instruction-override",
    "generic-injection",
}


@pytest.fixture(scope="module")
def corpus() -> dict:
    assert _CORPUS.is_file(), f"missing corpus fixture: {_CORPUS}"
    return json.loads(_CORPUS.read_text(encoding="utf-8"))


def test_corpus_parses_and_has_schema(corpus: dict) -> None:
    assert corpus["schema_version"] == 1
    assert corpus["corpus_id"] == "promptfoo-prompt-injection"
    assert isinstance(corpus["templates"], list) and corpus["templates"], "empty templates"


def test_counts_are_pinned_and_true(corpus: dict) -> None:
    templates = corpus["templates"]
    with_ph = sum(1 for t in templates if _PLACEHOLDER in t["template"])
    without_ph = len(templates) - with_ph

    # Pinned constants — a dropped or added entry fails loud here.
    assert corpus["counts"]["total"] == _PIN_TOTAL
    assert corpus["counts"]["with_placeholder"] == _PIN_WITH_PLACEHOLDER
    assert corpus["counts"]["without_placeholder"] == _PIN_WITHOUT_PLACEHOLDER

    # Declared counts must match reality, and reality must match the pins.
    assert len(templates) == _PIN_TOTAL
    assert corpus["counts"]["total"] == len(templates)
    assert with_ph == _PIN_WITH_PLACEHOLDER
    assert without_ph == _PIN_WITHOUT_PLACEHOLDER


def test_content_hash_is_pinned_and_matches(corpus: dict) -> None:
    # Recompute the integrity hash exactly as the builder did: every template
    # in source order, NUL-joined. Catches any content edit or reorder.
    ordered = [t["template"] for t in sorted(corpus["templates"], key=lambda t: t["source_index"])]
    digest = hashlib.sha256("\x00".join(ordered).encode("utf-8")).hexdigest()
    assert corpus["content_sha256"] == _PIN_CONTENT_SHA256, "fixture's own hash drifted from the pin"
    assert digest == _PIN_CONTENT_SHA256, "recomputed content hash != pin — templates were mutated"


def test_provenance_is_pinned(corpus: dict) -> None:
    prov = corpus["provenance"]
    assert "promptfoo/promptfoo" in prov["source_repo"]
    assert prov["source_path"] == _PIN_SOURCE_PATH
    assert prov["source_commit"] == _PIN_SOURCE_COMMIT
    assert prov["source_blob_sha"] == _PIN_SOURCE_BLOB_SHA
    assert prov["source_bytes"] == 232021
    assert prov["license"] == "MIT"
    # Attribution names both parties.
    attrib = prov["attribution"]
    assert "Promptfoo" in attrib["promptfoo"]
    assert _PIN_LLMGUARD_COMMIT in attrib["protectai_llm_guard"]


def test_both_notices_ship_and_carry_required_text() -> None:
    assert _LICENSE.is_file(), "promptfoo MIT license file missing"
    lic = _LICENSE.read_text(encoding="utf-8")
    assert "Permission is hereby granted" in lic
    assert "Promptfoo" in lic

    assert _NOTICE.is_file(), "attribution NOTICE missing"
    notice = _NOTICE.read_text(encoding="utf-8")
    # The Protect AI / llm-guard MIT notice must be reproduced, pinned to its commit.
    assert "Protect AI" in notice
    assert _PIN_LLMGUARD_COMMIT in notice
    assert "Permission is hereby granted" in notice


def test_every_entry_is_well_formed(corpus: dict) -> None:
    templates = corpus["templates"]
    seen_ids: set[str] = set()
    for i, t in enumerate(templates):
        loc = f"entry #{i}"
        # Identity + ordering.
        assert t["source_index"] == i, f"{loc}: source_index != position"
        assert t["id"] not in seen_ids, f"{loc}: duplicate id {t['id']}"
        seen_ids.add(t["id"])
        # Template text.
        assert isinstance(t["template"], str) and t["template"].strip(), f"{loc}: empty template"
        # Placeholder bookkeeping must match the actual text.
        actual = t["template"].count(_PLACEHOLDER)
        assert t["placeholder_count"] == actual, f"{loc}: placeholder_count mismatch"
        assert t["has_placeholder"] == (actual > 0), f"{loc}: has_placeholder mismatch"
        # Technique tag from the known (local-heuristic) enum, clearly sourced.
        assert t["technique"] in _KNOWN_TECHNIQUES, f"{loc}: unknown technique {t['technique']!r}"
        assert t["technique_source"] == "local-heuristic", f"{loc}: technique_source not labelled local"
        assert t["byte_length"] == len(t["template"].encode("utf-8")), f"{loc}: byte_length wrong"


def test_placeholder_and_selfcontained_partition(corpus: dict) -> None:
    # Entry 0 is upstream's default "skeleton key".
    assert corpus["templates"][0]["technique"] == "skeleton-key"
    for t in corpus["templates"]:
        if t["has_placeholder"]:
            assert _PLACEHOLDER in t["template"]
        else:
            assert _PLACEHOLDER not in t["template"]
