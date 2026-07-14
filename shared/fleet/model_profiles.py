"""Loader for the model-profiles manifest (``agentic-setup/configs/model-profiles.json``).

The manifest carries per-model attributes (architecture / family / quant /
serving-backend / tool-call format / thinking-mode / cost-profile / ...) so the
harness can branch on *what model it is driving*, not only on task complexity.
See ``agentic-setup/configs/model-profiles.json`` (its ``note``) and the design
dossier ``docs/handoffs/research-model-profiles-20260711.md`` (sec 5 taxonomy,
sec 7 manifest design) authored under Vikunja #834.

DORMANT by default. The ONLY field any BlarAI consumer reads as of #834 is the
AO brain's reasoning-strip tags — the ``<think>`` / ``<tool_call>`` hidden-block
strip shared by ``entrypoint._strip_hidden_blocks`` and
``gpu_inference._visible_text``. Every other field is reference data that later
tickets adopt one field at a time, each its own reviewed change.

FAIL-SOFT is the load-bearing property. The manifest lives in the *sibling*
``agentic-setup`` repo; on any box where that repo is not checked out at the
compiled-in path (an isolated worktree, CI, a fresh clone) the file is simply
absent. A missing / unreadable / malformed / partial manifest therefore resolves
to the **byte-identical historical hard-coded values**, so landing this loader
changes nothing observable. Every public function swallows all exceptions and
returns the conservative default; NONE may raise — they run in the AO boot path,
at import time, where a raise would refuse-to-start the orchestrator.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

# The this-host fallback root, mirroring ``shared/fleet/dispatch.py::_AGENTIC_SETUP``
# (a single-host system; the dispatch target root is the same box's agentic-setup).
_AGENTIC_SETUP = Path(r"C:\Users\mrbla\agentic-setup")

#: Compiled-in default location of the manifest.
DEFAULT_PROFILES_PATH: Path = _AGENTIC_SETUP / "configs" / "model-profiles.json"

#: Env override so tests and non-default checkouts can point at another copy
#: (e.g. a worktree's manifest) without editing the compiled-in default.
ENV_OVERRIDE: str = "BLARAI_MODEL_PROFILES_PATH"

#: The AO brain: the in-proc dense 14B that plans / grades / answers and whose
#: ``<think>`` / ``<tool_call>`` blocks the AO strips. Kept as ONE named constant
#: rather than a string scattered across consumers.
AO_BRAIN_MODEL_ID: str = "qwen3-14b"

#: Byte-identical historical default. ``entrypoint.py`` and ``gpu_inference.py``
#: both hard-coded ``re.compile(r"<think>.*?</think>|<tool_call>.*?</tool_call>",
#: re.DOTALL)`` — these two tags, in this order, rebuild exactly that pattern.
DEFAULT_HIDDEN_BLOCK_TAGS: tuple[str, ...] = ("think", "tool_call")

# Never-matching pattern for the (defensive) empty-tag case — ``\b\B`` asserts a
# word boundary AND a non-boundary at the same position, which is impossible.
_NEVER_MATCH: "re.Pattern[str]" = re.compile(r"\b\B")


@dataclass(frozen=True)
class ModelProfile:
    """One served model's stable attributes (the promoted, typed subset).

    ``raw`` keeps the full manifest entry so fields not promoted here stay
    reachable without a loader change.
    """

    model_id: str
    family: str
    arch: str
    serving_backend: str
    tool_call_format: str
    thinking_mode: str
    grammar_support: str
    context_window: int
    effective_context: int
    max_output_tokens: int
    resident_gb: int
    roles: tuple[str, ...]
    hidden_block_tags: tuple[str, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ModelProfiles:
    """Parsed manifest: the two tables plus the raw document."""

    schema: str
    defaults: Mapping[str, Any]
    models: Mapping[str, ModelProfile]
    call_sites: Mapping[str, Mapping[str, Any]]
    raw: Mapping[str, Any]

    def model(self, model_id: str) -> "ModelProfile | None":
        return self.models.get(model_id)


def resolve_profiles_path(path: "str | Path | None" = None) -> Path:
    """The manifest path to read: explicit arg > env override > compiled default."""
    if path is not None:
        return Path(path)
    env = os.environ.get(ENV_OVERRIDE)
    if env:
        return Path(env)
    return DEFAULT_PROFILES_PATH


def _tags_from_mapping(
    entry: Any, fallback: tuple[str, ...]
) -> tuple[str, ...]:
    """Extract a non-empty list of non-empty string tags from an entry's
    ``reasoning_strip.hidden_block_tags``; any deviation falls back."""
    if not isinstance(entry, Mapping):
        return fallback
    rs = entry.get("reasoning_strip")
    if not isinstance(rs, Mapping):
        return fallback
    tags = rs.get("hidden_block_tags")
    if (
        isinstance(tags, list)
        and tags  # reject an empty list — strip-nothing is not the historical default
        and all(isinstance(t, str) and t for t in tags)
    ):
        return tuple(tags)
    return fallback


def _as_int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _as_str(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _parse_model(
    model_id: str, entry: Any, defaults: Mapping[str, Any]
) -> ModelProfile:
    """Build a typed profile, each field fail-soft to the manifest ``defaults``
    then the module conservative default. Never raises."""
    e: Mapping[str, Any] = entry if isinstance(entry, Mapping) else {}

    def field_str(key: str, hard: str) -> str:
        return _as_str(e.get(key), _as_str(defaults.get(key), hard))

    def field_int(key: str, hard: int) -> int:
        return _as_int(e.get(key), _as_int(defaults.get(key), hard))

    roles_raw = e.get("roles")
    roles = tuple(r for r in roles_raw if isinstance(r, str)) if isinstance(roles_raw, list) else ()

    defaults_tags = _tags_from_mapping(defaults, DEFAULT_HIDDEN_BLOCK_TAGS)
    hidden_tags = _tags_from_mapping(e, defaults_tags)

    return ModelProfile(
        model_id=model_id,
        family=field_str("family", "unknown"),
        arch=field_str("arch", "dense"),
        serving_backend=field_str("serving_backend", "ovms"),
        tool_call_format=field_str("tool_call_format", "hermes"),
        thinking_mode=field_str("thinking_mode", "none"),
        grammar_support=field_str("grammar_support", "none"),
        context_window=field_int("context_window", 32768),
        effective_context=field_int("effective_context", field_int("context_window", 32768)),
        max_output_tokens=field_int("max_output_tokens", 8192),
        resident_gb=field_int("resident_gb", 10),
        roles=roles,
        hidden_block_tags=hidden_tags,
        raw=e,
    )


def load_model_profiles(path: "str | Path | None" = None) -> "ModelProfiles | None":
    """Read + parse the manifest. Returns ``None`` on ANY failure (absent file,
    unreadable, non-JSON, wrong shape). Never raises."""
    try:
        p = resolve_profiles_path(path)
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
        models_raw = raw.get("models") if isinstance(raw.get("models"), dict) else {}
        call_sites = raw.get("call_sites") if isinstance(raw.get("call_sites"), dict) else {}
        models = {
            mid: _parse_model(mid, entry, defaults)
            for mid, entry in models_raw.items()
            if isinstance(mid, str)
        }
        return ModelProfiles(
            schema=_as_str(raw.get("schema"), ""),
            defaults=defaults,
            models=models,
            call_sites=call_sites,
            raw=raw,
        )
    except Exception:  # noqa: BLE001 — fail-soft: any error → "no manifest"
        return None


def hidden_block_re(tags: Sequence[str]) -> "re.Pattern[str]":
    """Build the DOTALL hidden-block alternation from tag names.

    ``("think", "tool_call")`` → ``re.compile(
    r"<think>.*?</think>|<tool_call>.*?</tool_call>", re.DOTALL)`` — byte-identical
    to the historical hard-coded pattern in ``entrypoint.py`` / ``gpu_inference.py``.
    An empty tag sequence yields a never-matching pattern (strip nothing).
    """
    if not tags:
        return _NEVER_MATCH
    alternation = "|".join(f"<{t}>.*?</{t}>" for t in tags)
    return re.compile(alternation, re.DOTALL)


def hidden_block_open_tags(tags: Sequence[str]) -> tuple[str, ...]:
    """The opening tags for the unclosed-block withholding in
    ``gpu_inference._visible_text``: ``("think","tool_call") → ("<think>","<tool_call>")``."""
    return tuple(f"<{t}>" for t in tags)


def resolve_hidden_block_tags(
    model_id: str = AO_BRAIN_MODEL_ID, *, path: "str | Path | None" = None
) -> tuple[str, ...]:
    """Resolve the hidden-block tags for *model_id* from the manifest, fail-soft
    to the manifest ``defaults`` then to the byte-identical hard-coded default.
    Never raises."""
    try:
        profiles = load_model_profiles(path)
        if profiles is None:
            return DEFAULT_HIDDEN_BLOCK_TAGS
        mp = profiles.model(model_id)
        if mp is not None:
            return mp.hidden_block_tags
        # model id not listed → the manifest defaults-level tags (then hard-coded)
        return _tags_from_mapping(profiles.defaults, DEFAULT_HIDDEN_BLOCK_TAGS)
    except Exception:  # noqa: BLE001 — fail-soft
        return DEFAULT_HIDDEN_BLOCK_TAGS


def resolve_hidden_block_re(
    model_id: str = AO_BRAIN_MODEL_ID, *, path: "str | Path | None" = None
) -> "re.Pattern[str]":
    """Convenience: the compiled DOTALL hidden-block regex for *model_id*,
    fail-soft to the byte-identical historical pattern. Never raises."""
    return hidden_block_re(resolve_hidden_block_tags(model_id, path=path))
