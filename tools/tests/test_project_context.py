"""Tests for tools/_project_context.py (Stage 2.2 resolution helper)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools._project_context import (
    DEFAULT_BLARAI_ROOT,
    ProjectContext,
    REGISTRY_RELATIVE,
    _load_registry,
    resolve,
)


def _write_registry(root: Path, payload: str) -> None:
    target = root / REGISTRY_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")


def test_load_registry_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _load_registry(tmp_path)


def test_resolve_with_explicit_cli_root(tmp_path: Path):
    project_dir = tmp_path / "blarai"
    project_dir.mkdir()
    _write_registry(project_dir, "blarai_project_id: 3\n")

    ctx = resolve(cli_root=project_dir)
    assert isinstance(ctx, ProjectContext)
    assert ctx.root == project_dir.resolve()
    assert ctx.vikunja_project_id == 3
    assert ctx.name == "blarai"


def test_resolve_cli_project_id_overrides_registry(tmp_path: Path):
    project_dir = tmp_path / "blarai"
    project_dir.mkdir()
    _write_registry(project_dir, "blarai_project_id: 3\n")

    ctx = resolve(cli_root=project_dir, cli_project_id=42)
    assert ctx.vikunja_project_id == 42


def test_resolve_rejects_bool_project_id(tmp_path: Path):
    project_dir = tmp_path / "evil"
    project_dir.mkdir()
    # YAML "true" parses to bool — must be rejected (cleanup-C3 alignment).
    _write_registry(project_dir, "evil_project_id: true\n")

    with pytest.raises(ValueError):
        resolve(cli_root=project_dir)


def test_resolve_rejects_string_project_id(tmp_path: Path):
    project_dir = tmp_path / "stringy"
    project_dir.mkdir()
    _write_registry(project_dir, "stringy_project_id: '7'\n")

    with pytest.raises(ValueError):
        resolve(cli_root=project_dir)


def test_resolve_falls_back_to_generic_project_id_key(tmp_path: Path):
    project_dir = tmp_path / "weirdname"
    project_dir.mkdir()
    # No "weirdname_project_id" key — falls through to generic "project_id".
    _write_registry(project_dir, "project_id: 9\n")

    ctx = resolve(cli_root=project_dir)
    assert ctx.vikunja_project_id == 9


def test_resolve_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project_dir = tmp_path / "envproj"
    project_dir.mkdir()
    _write_registry(project_dir, "envproj_project_id: 11\n")

    monkeypatch.setenv("BLARAI_PROJECT_ROOT", str(project_dir))
    ctx = resolve()
    assert ctx.root == project_dir.resolve()
    assert ctx.vikunja_project_id == 11


def test_default_blarai_root_constant():
    """Defaults-preservation: the hard-coded fallback must remain BlarAI's root."""
    assert DEFAULT_BLARAI_ROOT == Path(r"C:\Users\mrbla\BlarAI")


def test_default_blarai_resolves_to_project_id_3(monkeypatch: pytest.MonkeyPatch):
    """Defaults-preservation: with no CLI args / env, the live BlarAI registry
    must still resolve to project_id=3 (Vikunja BlarAI Core Development)."""
    monkeypatch.delenv("BLARAI_PROJECT_ROOT", raising=False)
    ctx = resolve(cli_root=DEFAULT_BLARAI_ROOT)
    assert ctx.vikunja_project_id == 3
    assert ctx.root == DEFAULT_BLARAI_ROOT.resolve()
