"""Gate: ``model-profiles.json`` agrees with its two SSOT mirrors (#834).

WHY THIS GATE EXISTS — the same class the passthrough-allowlist test was minted
to kill (``test_winui_passthrough_allowlist.py``): a per-model fact hand-copied
into more than one file drifts silently.  ``agentic-setup/configs/model-profiles.json``
is a SUPERSET of two surfaces that already carry the same facts:

  * ``configs/opencode.json`` (``provider.local.models``) — what opencode consumes;
    the overlapping fields ``tool_call`` / ``reasoning`` / ``limit.context`` /
    ``limit.output`` MUST agree with the profile.
  * ``scripts/start-llm.ps1`` — the hand-wired OVMS launch: ``--tool_parser`` per
    model, the ``$residentGB`` table, and the MoE ``MOE_USE_MICRO_GEMM_PREFILL``
    env.  These MUST agree with the profile's ``tool_call_format`` / ``resident_gb``
    / ``arch``.

The comparison is a PURE function (``compute_ssot_mismatches``) so its teeth are
proven hermetically (``test_ssot_comparison_has_teeth``) regardless of whether the
sibling ``agentic-setup`` checkout is present.  The live cross-file check runs when
the manifest is resolvable (the #834 targeted run via ``BLARAI_MODEL_PROFILES_PATH``,
or the merged agentic-setup checkout) and SKIPS otherwise — exactly like the
passthrough gate skips without ``MainWindow.xaml.cs``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import pytest

from shared.fleet.model_profiles import resolve_profiles_path

# ── SSOT mapping constants ─────────────────────────────────────────────────
# start-llm.ps1 chooses an OVMS ``--tool_parser`` per model; the profile records
# the abstract ``tool_call_format``.  This is the agreed translation between them.
_PARSER_TO_FORMAT: dict[str, str] = {
    "hermes3": "hermes",
    "qwen3coder": "qwen3_xml",
}

_BRANCH_HDR = re.compile(r"'(coder-30b|qwen3-14b|vision)'\s*\{")
_TOOL_PARSER = re.compile(r"'--tool_parser'\s*,\s*'([^']+)'")
_RESIDENT_BLOCK = re.compile(r"residentGB\s*=\s*@\{(.*?)\}", re.DOTALL)
_RESIDENT_PAIR = re.compile(r"'([^']+)'\s*=\s*(\d+)")


# ── parsers for the two mirror surfaces ────────────────────────────────────

def _opencode_local_models(opencode_raw: Mapping[str, Any]) -> dict[str, Any]:
    try:
        models = opencode_raw["provider"]["local"]["models"]
    except (KeyError, TypeError):
        return {}
    return dict(models) if isinstance(models, Mapping) else {}


def _startllm_tool_parsers(text: str) -> dict[str, str]:
    """Attribute each ``--tool_parser`` to the nearest preceding switch-branch id."""
    headers = [(m.start(), m.group(1)) for m in _BRANCH_HDR.finditer(text)]
    result: dict[str, str] = {}
    for pm in _TOOL_PARSER.finditer(text):
        owner = None
        for hpos, hid in headers:
            if hpos < pm.start():
                owner = hid
            else:
                break
        if owner is not None:
            result[owner] = pm.group(1)
    return result


def _startllm_resident_gb(text: str) -> dict[str, int]:
    m = _RESIDENT_BLOCK.search(text)
    if not m:
        return {}
    return {mid: int(gb) for mid, gb in _RESIDENT_PAIR.findall(m.group(1))}


# ── the pure comparator (the teeth) ────────────────────────────────────────

def compute_ssot_mismatches(
    profiles_raw: Mapping[str, Any],
    opencode_raw: Mapping[str, Any],
    startllm_text: str,
) -> list[str]:
    """Return a list of human-readable drift descriptions; empty == agreement."""
    out: list[str] = []
    prof_models: Mapping[str, Any] = profiles_raw.get("models", {}) or {}
    oc_models = _opencode_local_models(opencode_raw)

    prof_ids, oc_ids = set(prof_models), set(oc_models)
    if prof_ids != oc_ids:
        out.append(
            "model-id set differs: "
            f"profile-only={sorted(prof_ids - oc_ids)} "
            f"opencode-only={sorted(oc_ids - prof_ids)}"
        )

    for mid in sorted(prof_ids & oc_ids):
        pm: Mapping[str, Any] = prof_models[mid] or {}
        om: Mapping[str, Any] = oc_models[mid] or {}
        limit = om.get("limit") or {}

        oc_tool = bool(om.get("tool_call", False))
        prof_tool = pm.get("tool_call_format", "none") != "none"
        if oc_tool != prof_tool:
            out.append(
                f"{mid}: tool_call opencode={oc_tool} vs "
                f"profile.tool_call_format={pm.get('tool_call_format')!r}"
            )

        oc_reason = bool(om.get("reasoning", False))
        prof_reason = pm.get("thinking_mode", "none") != "none"
        if oc_reason != prof_reason:
            out.append(
                f"{mid}: reasoning opencode={oc_reason} vs "
                f"profile.thinking_mode={pm.get('thinking_mode')!r}"
            )

        prof_ctx = pm.get("effective_context", pm.get("context_window"))
        if limit.get("context") != prof_ctx:
            out.append(
                f"{mid}: limit.context opencode={limit.get('context')} vs "
                f"profile.effective_context={prof_ctx}"
            )

        if limit.get("output") != pm.get("max_output_tokens"):
            out.append(
                f"{mid}: limit.output opencode={limit.get('output')} vs "
                f"profile.max_output_tokens={pm.get('max_output_tokens')}"
            )

    for mid, parser in _startllm_tool_parsers(startllm_text).items():
        pm = prof_models.get(mid)
        if pm is None:
            out.append(f"start-llm names tool_parser for {mid!r} but the profile has no such model")
            continue
        expected = _PARSER_TO_FORMAT.get(parser)
        if expected is None:
            out.append(
                f"start-llm --tool_parser {parser!r} (for {mid}) is not in the SSOT "
                "translation map — extend _PARSER_TO_FORMAT"
            )
        elif pm.get("tool_call_format") != expected:
            out.append(
                f"{mid}: start-llm --tool_parser {parser!r} -> {expected!r} vs "
                f"profile.tool_call_format={pm.get('tool_call_format')!r}"
            )

    for mid, gb in _startllm_resident_gb(startllm_text).items():
        pm = prof_models.get(mid)
        if pm is not None and pm.get("resident_gb") != gb:
            out.append(
                f"{mid}: start-llm residentGB={gb} vs profile.resident_gb={pm.get('resident_gb')}"
            )

    if "MOE_USE_MICRO_GEMM_PREFILL" in startllm_text:
        moe_ids = [mid for mid, pm in prof_models.items() if (pm or {}).get("arch") == "moe"]
        if "coder-30b" not in moe_ids:
            out.append(
                "start-llm sets MOE_USE_MICRO_GEMM_PREFILL (the MoE workaround) but "
                "profile coder-30b.arch is not 'moe'"
            )

    return out


# ── file resolution (agentic-setup root = <manifest>/../..) ─────────────────

def _agentic_root() -> Path:
    return resolve_profiles_path().resolve().parent.parent


def _manifest_path() -> Path:
    return resolve_profiles_path()


def _live_files_present() -> bool:
    root = _agentic_root()
    return (
        _manifest_path().exists()
        and (root / "configs" / "opencode.json").exists()
        and (root / "scripts" / "start-llm.ps1").exists()
    )


_SKIP_REASON = (
    "model-profiles.json / opencode.json / start-llm.ps1 not all resolvable at the "
    "agentic-setup path (set BLARAI_MODEL_PROFILES_PATH, or run after the "
    "agentic-setup merge)"
)


# ── live cross-file check (skips without the sibling checkout) ──────────────

@pytest.mark.skipif(not _live_files_present(), reason=_SKIP_REASON)
def test_profiles_agree_with_opencode_and_startllm() -> None:
    root = _agentic_root()
    profiles_raw = json.loads(_manifest_path().read_text(encoding="utf-8"))
    opencode_raw = json.loads((root / "configs" / "opencode.json").read_text(encoding="utf-8"))
    startllm_text = (root / "scripts" / "start-llm.ps1").read_text(encoding="utf-8")

    mismatches = compute_ssot_mismatches(profiles_raw, opencode_raw, startllm_text)
    assert not mismatches, (
        "model-profiles.json has drifted from its SSOT mirrors "
        "(opencode.json / start-llm.ps1):\n  - " + "\n  - ".join(mismatches)
    )


@pytest.mark.skipif(not _live_files_present(), reason=_SKIP_REASON)
def test_live_parsers_found_the_real_facts() -> None:
    """Guard a vacuous pass: the mirror parsers must actually extract the known
    hand-wired facts from the real start-llm.ps1."""
    startllm_text = (_agentic_root() / "scripts" / "start-llm.ps1").read_text(encoding="utf-8")
    parsers = _startllm_tool_parsers(startllm_text)
    assert parsers.get("qwen3-14b") == "hermes3"
    assert parsers.get("coder-30b") == "qwen3coder"
    assert _startllm_resident_gb(startllm_text).get("coder-30b") == 18


# ── hermetic teeth: the comparator detects each drift class ─────────────────

def _agreeing_trio() -> tuple[dict, dict, str]:
    profiles = {
        "models": {
            "coder-30b": {
                "arch": "moe", "tool_call_format": "qwen3_xml", "thinking_mode": "none",
                "effective_context": 65536, "max_output_tokens": 16384, "resident_gb": 18,
            },
            "qwen3-14b": {
                "arch": "dense", "tool_call_format": "hermes", "thinking_mode": "optional",
                "effective_context": 32768, "max_output_tokens": 8192, "resident_gb": 10,
            },
        }
    }
    opencode = {
        "provider": {"local": {"models": {
            "coder-30b": {"tool_call": True, "reasoning": False,
                          "limit": {"context": 65536, "output": 16384}},
            "qwen3-14b": {"tool_call": True, "reasoning": True,
                          "limit": {"context": 32768, "output": 8192}},
        }}}
    }
    startllm = (
        "switch ($Model) {\n"
        "  'coder-30b' {\n    $extra=@('--tool_parser','qwen3coder')\n"
        "    $env:MOE_USE_MICRO_GEMM_PREFILL = '0'\n  }\n"
        "  'qwen3-14b' {\n    $extra=@('--tool_parser','hermes3')\n  }\n}\n"
        "$residentGB = @{ 'coder-30b' = 18; 'qwen3-14b' = 10; 'qwen3-vl-8b' = 6 }\n"
    )
    return profiles, opencode, startllm


def test_agreeing_trio_has_no_mismatches() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    assert compute_ssot_mismatches(profiles, opencode, startllm) == []


def test_teeth_id_set_drift() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    del profiles["models"]["qwen3-14b"]
    m = compute_ssot_mismatches(profiles, opencode, startllm)
    assert any("model-id set differs" in x for x in m)


def test_teeth_tool_call_drift() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    profiles["models"]["qwen3-14b"]["tool_call_format"] = "none"  # says "no tools"
    m = compute_ssot_mismatches(profiles, opencode, startllm)
    assert any("qwen3-14b: tool_call" in x for x in m)


def test_teeth_context_drift() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    profiles["models"]["coder-30b"]["effective_context"] = 12345
    m = compute_ssot_mismatches(profiles, opencode, startllm)
    assert any("coder-30b: limit.context" in x for x in m)


def test_teeth_output_drift() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    profiles["models"]["qwen3-14b"]["max_output_tokens"] = 4096
    m = compute_ssot_mismatches(profiles, opencode, startllm)
    assert any("qwen3-14b: limit.output" in x for x in m)


def test_teeth_tool_parser_drift() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    profiles["models"]["coder-30b"]["tool_call_format"] = "hermes"  # start-llm says qwen3coder
    m = compute_ssot_mismatches(profiles, opencode, startllm)
    assert any("start-llm --tool_parser 'qwen3coder'" in x for x in m)


def test_teeth_resident_gb_drift() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    profiles["models"]["coder-30b"]["resident_gb"] = 99
    m = compute_ssot_mismatches(profiles, opencode, startllm)
    assert any("coder-30b: start-llm residentGB=18 vs profile.resident_gb=99" in x for x in m)


def test_teeth_moe_arch_drift() -> None:
    profiles, opencode, startllm = _agreeing_trio()
    profiles["models"]["coder-30b"]["arch"] = "dense"  # but start-llm sets the MoE env
    m = compute_ssot_mismatches(profiles, opencode, startllm)
    assert any("MOE_USE_MICRO_GEMM_PREFILL" in x for x in m)
