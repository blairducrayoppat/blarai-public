"""Unit tests for ``shared.fleet.model_profiles`` (#834).

The load-bearing property is FAIL-SOFT byte-identity: a missing / unreadable /
malformed / partial manifest must resolve to exactly the historical hard-coded
``<think>`` / ``<tool_call>`` strip regex, so landing the loader changes nothing
observable. These are hermetic — they write manifests to ``tmp_path`` and never
touch the sibling ``agentic-setup`` checkout.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from shared.fleet import model_profiles as mp

# The exact historical pattern both consumers hard-coded before #834.
_HISTORICAL = re.compile(r"<think>.*?</think>|<tool_call>.*?</tool_call>", re.DOTALL)


def _write(tmp_path: Path, obj: object) -> Path:
    p = tmp_path / "model-profiles.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _is_historical(pattern: "re.Pattern[str]") -> bool:
    return pattern.pattern == _HISTORICAL.pattern and pattern.flags == _HISTORICAL.flags


# ── fail-soft: the byte-identity contract ──────────────────────────────────

def test_absent_file_resolves_to_historical(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    assert _is_historical(mp.resolve_hidden_block_re(path=missing))
    assert mp.resolve_hidden_block_tags(path=missing) == mp.DEFAULT_HIDDEN_BLOCK_TAGS


def test_malformed_json_resolves_to_historical(tmp_path: Path) -> None:
    p = tmp_path / "model-profiles.json"
    p.write_text("{ this is not valid json ", encoding="utf-8")
    assert _is_historical(mp.resolve_hidden_block_re(path=p))
    assert mp.load_model_profiles(p) is None


def test_non_dict_json_resolves_to_historical(tmp_path: Path) -> None:
    p = _write(tmp_path, ["not", "an", "object"])
    assert _is_historical(mp.resolve_hidden_block_re(path=p))
    assert mp.load_model_profiles(p) is None


def test_present_manifest_is_byte_identical(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "models": {
                "qwen3-14b": {"reasoning_strip": {"hidden_block_tags": ["think", "tool_call"]}}
            }
        },
    )
    assert _is_historical(mp.resolve_hidden_block_re(mp.AO_BRAIN_MODEL_ID, path=p))


def test_missing_reasoning_strip_uses_manifest_defaults(tmp_path: Path) -> None:
    # model entry has no reasoning_strip → the defaults-level tags apply.
    p = _write(
        tmp_path,
        {
            "defaults": {"reasoning_strip": {"hidden_block_tags": ["think", "tool_call"]}},
            "models": {"qwen3-14b": {"arch": "dense"}},
        },
    )
    assert mp.resolve_hidden_block_tags(path=p) == ("think", "tool_call")
    assert _is_historical(mp.resolve_hidden_block_re(path=p))


def test_unknown_model_id_uses_defaults(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "defaults": {"reasoning_strip": {"hidden_block_tags": ["think", "tool_call"]}},
            "models": {"some-other-model": {"reasoning_strip": {"hidden_block_tags": ["x"]}}},
        },
    )
    assert mp.resolve_hidden_block_tags("qwen3-14b", path=p) == ("think", "tool_call")


def test_empty_tags_list_rejected_falls_back(tmp_path: Path) -> None:
    # An explicit empty list is NOT the historical strip-both default → reject it.
    p = _write(
        tmp_path,
        {"models": {"qwen3-14b": {"reasoning_strip": {"hidden_block_tags": []}}}},
    )
    assert mp.resolve_hidden_block_tags(path=p) == mp.DEFAULT_HIDDEN_BLOCK_TAGS


def test_malformed_tags_type_rejected_falls_back(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {"models": {"qwen3-14b": {"reasoning_strip": {"hidden_block_tags": "think"}}}},
    )
    assert mp.resolve_hidden_block_tags(path=p) == mp.DEFAULT_HIDDEN_BLOCK_TAGS


# ── the data-driven path (a swap edits tags) ───────────────────────────────

def test_custom_tags_build_expected_regex() -> None:
    r = mp.hidden_block_re(("reason", "call"))
    assert r.pattern == "<reason>.*?</reason>|<call>.*?</call>"
    assert r.flags == _HISTORICAL.flags  # DOTALL (+ implicit UNICODE)


def test_custom_tags_resolve_from_manifest(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {"models": {"qwen3-14b": {"reasoning_strip": {"hidden_block_tags": ["reason"]}}}},
    )
    assert mp.resolve_hidden_block_tags(path=p) == ("reason",)
    assert mp.resolve_hidden_block_re(path=p).pattern == "<reason>.*?</reason>"


def test_open_tags_helper() -> None:
    assert mp.hidden_block_open_tags(("think", "tool_call")) == ("<think>", "<tool_call>")


def test_empty_tags_never_match() -> None:
    r = mp.hidden_block_re(())
    assert r.search("<think>x</think>") is None


# ── typed parse ────────────────────────────────────────────────────────────

def test_load_parses_typed_fields(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "schema": "model-profile/v1",
            "defaults": {"arch": "dense"},
            "models": {
                "coder-30b": {
                    "family": "qwen3",
                    "arch": "moe",
                    "serving_backend": "ovms",
                    "tool_call_format": "qwen3_xml",
                    "thinking_mode": "none",
                    "grammar_support": "tool_guided",
                    "context_window": 262144,
                    "effective_context": 65536,
                    "max_output_tokens": 16384,
                    "resident_gb": 18,
                    "roles": ["coder"],
                }
            },
            "call_sites": {"coder": {"model": "coder-30b"}},
        },
    )
    prof = mp.load_model_profiles(p)
    assert prof is not None
    assert prof.schema == "model-profile/v1"
    m = prof.model("coder-30b")
    assert m is not None
    assert m.arch == "moe"
    assert m.serving_backend == "ovms"
    assert m.tool_call_format == "qwen3_xml"
    assert m.effective_context == 65536
    assert m.max_output_tokens == 16384
    assert m.resident_gb == 18
    assert m.roles == ("coder",)
    assert "coder" in prof.call_sites


def test_effective_context_falls_back_to_context_window(tmp_path: Path) -> None:
    p = _write(tmp_path, {"models": {"m": {"context_window": 12345}}})
    prof = mp.load_model_profiles(p)
    assert prof is not None
    assert prof.model("m").effective_context == 12345


def test_path_precedence_explicit_over_env(tmp_path: Path, monkeypatch) -> None:
    explicit = tmp_path / "explicit.json"
    monkeypatch.setenv(mp.ENV_OVERRIDE, str(tmp_path / "env.json"))
    assert mp.resolve_profiles_path(explicit) == explicit


def test_path_precedence_env_over_default(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / "env.json"
    monkeypatch.setenv(mp.ENV_OVERRIDE, str(env))
    assert mp.resolve_profiles_path() == env


# ── the SHIPPED manifest (skips if agentic-setup not at the resolved path) ──

def test_shipped_manifest_strip_is_byte_identical() -> None:
    """If a real manifest is resolvable (env override in the #834 targeted run, or
    the merged agentic-setup checkout), its assistant-role model MUST rebuild the
    byte-identical historical strip — the regression lock the ticket asks for."""
    prof = mp.load_model_profiles()
    if prof is None:
        pytest.skip("model-profiles.json not resolvable at the default/env path")
    assert _is_historical(mp.resolve_hidden_block_re(mp.AO_BRAIN_MODEL_ID))
