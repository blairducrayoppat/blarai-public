"""The reference corpus ships DORMANT, and dormancy is structural (#1616).

A new capability merges behind a flag and waits for an LA-present ceremony.
That is easy to claim and easy to get subtly wrong, so each property here is
asserted against the shipped artefacts rather than against intent:

  * the shipped config really says false;
  * with no runner registered the tool returns a notice and reaches no store;
  * the tool is nevertheless on the allowlist, so a model emission meets the
    layered refusal instead of leaking raw ``<tool_call>`` text to the user;
  * a store that fails integrity verification is NOT served.

The last one is the point of decision D1: the corpus is integrity-signed
rather than encrypted, so verification is the only thing standing between the
assistant and confidently citing a corrupted or swapped file.
"""

from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path

import pytest

from services.assistant_orchestrator.src import tools
from services.assistant_orchestrator.src.context_manager import Provenance
from services.assistant_orchestrator.src.pgov import TOOL_CALL_ALLOWLIST
from shared.corpus import CorpusError, ReferenceCorpus
from tools.corpus.build_corpus import build, write_manifest

_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "assistant_orchestrator"
    / "config"
    / "default.toml"
)


class TestShippedConfigIsDormant:
    def test_flag_is_false_in_the_shipped_config(self) -> None:
        cfg = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
        section = cfg.get("reference_corpus", {})
        assert section.get("enabled") is False, (
            "reference_corpus.enabled must ship false — this is a NEW "
            "capability and its go-live is an LA-present ceremony (#1616)"
        )

    def test_no_store_path_is_shipped(self) -> None:
        cfg = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
        section = cfg.get("reference_corpus", {})
        assert section.get("db_path", "") == ""
        assert section.get("manifest_path", "") == ""


class TestStructuralDormancy:
    def test_tool_returns_a_notice_with_no_runner(self) -> None:
        """Dormancy is the ABSENCE of a runner, not a flag checked at call time."""
        tools.clear_search_reference_runner()
        out = tools._REGISTRY["search_reference"](json.dumps({"query": "greece"}))
        assert out == tools.SEARCH_REFERENCE_UNAVAILABLE_NOTICE

    def test_tool_is_allowlisted_so_a_model_emission_is_refused_properly(self) -> None:
        """Absent from the allowlist, a model emitting this tool would have its
        raw <tool_call> text surface as the answer instead of meeting the
        layered refusal. Dormant must not mean unlisted."""
        assert "search_reference" in TOOL_CALL_ALLOWLIST

    def test_tool_has_a_schema(self) -> None:
        assert tools.arguments_schema("search_reference") is not None

    def test_runner_errors_become_a_notice_never_an_exception(self) -> None:
        def _boom(query: str, max_results: int) -> str:
            raise RuntimeError("store exploded")

        tools.register_search_reference_runner(_boom)
        try:
            out = tools._REGISTRY["search_reference"](json.dumps({"query": "x"}))
            assert out == tools.SEARCH_REFERENCE_ERROR_NOTICE
        finally:
            tools.clear_search_reference_runner()

    def test_empty_result_becomes_a_notice_not_silence(self) -> None:
        """An empty string would read to the model as settled coverage — a
        confident falsehood about what the encyclopedia contains."""
        tools.register_search_reference_runner(lambda q, k: "")
        try:
            out = tools._REGISTRY["search_reference"](json.dumps({"query": "x"}))
            assert out == tools.SEARCH_REFERENCE_NO_RESULTS_NOTICE
        finally:
            tools.clear_search_reference_runner()

    def test_result_is_capped_at_the_retrieval_budget(self) -> None:
        tools.register_search_reference_runner(lambda q, k: "z" * 99_000)
        try:
            out = tools._REGISTRY["search_reference"](json.dumps({"query": "x"}))
            assert len(out) == tools.RETRIEVAL_RESULT_MAX_CHARS
        finally:
            tools.clear_search_reference_runner()


class TestCorpusIsNotServedUnverified:
    """D1's fail-closed half, driven through the real reader."""

    @staticmethod
    def _make(tmp_path: Path) -> Path:
        jsonl = tmp_path / "in.jsonl"
        jsonl.write_text(
            json.dumps(
                {
                    "k": "chunk",
                    "t": "Ancient Greece",
                    "p": "greece",
                    "s": "",
                    "x": "Ancient Greece was a civilization of the Mediterranean "
                    "world, comprising a loose collection of city states.",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        db = tmp_path / "corpus.db"
        (tmp_path / "in.jsonl.meta.json").write_text(
            json.dumps(
                {"source_name": "wikipedia_en_test", "archive_date": "2026-08-25"}
            ),
            encoding="utf-8",
        )
        build([str(jsonl)], str(db))
        return db

    def test_a_tampered_store_is_refused(self, tmp_path: Path) -> None:
        db = self._make(tmp_path)
        manifest = tmp_path / "corpus.manifest.json"
        write_manifest(str(db), str(manifest))

        # Tamper AFTER the manifest is written — the realistic shape.
        conn = sqlite3.connect(db)
        conn.execute("UPDATE meta SET value='999' WHERE key='chunk_count'")
        conn.commit()
        conn.close()

        with pytest.raises(CorpusError, match="integrity"):
            ReferenceCorpus(db, manifest_path=manifest)

    def test_the_same_probe_passes_on_an_untampered_store(self, tmp_path: Path) -> None:
        """Toggle half: without this, the test above proves only that the
        reader is capable of raising."""
        db = self._make(tmp_path)
        manifest = tmp_path / "corpus.manifest.json"
        write_manifest(str(db), str(manifest))
        with ReferenceCorpus(db, manifest_path=manifest) as corpus:
            assert corpus.chunk_count == 1


    def test_an_empty_manifest_setting_cannot_open_an_unverified_store(
        self, tmp_path: Path
    ) -> None:
        """#1616 pre-merge review finding 2: ``[reference_corpus].manifest_path =
        ""`` reached the reader as None and opened the store UNVERIFIED. The
        shipped empty value is driven through the reader with the same
        ``configured or None`` shape the entrypoint uses (a retyped copy, not a
        call into it): with no manifest beside the store the reader refuses, and
        the reader has no unverified path for any shape."""
        db = self._make(tmp_path)
        configured = ""
        with pytest.raises(CorpusError, match="manifest missing"):
            ReferenceCorpus(db, manifest_path=configured or None)

    def test_an_empty_manifest_setting_verifies_the_builders_manifest(
        self, tmp_path: Path
    ) -> None:
        """Toggle half: the same empty setting opens once the builder's manifest
        is beside the store, and a tampered store beside it is refused."""
        from shared.corpus import default_manifest_path

        db = self._make(tmp_path)
        write_manifest(str(db), str(default_manifest_path(db)))
        configured = ""
        with ReferenceCorpus(db, manifest_path=configured or None) as corpus:
            assert corpus.chunk_count == 1
        conn = sqlite3.connect(db)
        conn.execute("UPDATE meta SET value='999' WHERE key='chunk_count'")
        conn.commit()
        conn.close()
        with pytest.raises(CorpusError, match="integrity"):
            ReferenceCorpus(db, manifest_path=configured or None)


class TestProvenanceTierExists:
    def test_corpus_tier_is_distinct_from_the_other_untrusted_tiers(self) -> None:
        """Amendment 5 keeps it separate so an audit can tell a bulk
        encyclopedia from the operator's own curated bank, even though the two
        gate identically today."""
        values = {
            Provenance.UNTRUSTED_CORPUS,
            Provenance.UNTRUSTED_KNOWLEDGE,
            Provenance.UNTRUSTED_WEB,
            Provenance.UNTRUSTED_EXTERNAL,
        }
        assert len(values) == 4
        assert Provenance.UNTRUSTED_CORPUS.value == "untrusted_corpus"
