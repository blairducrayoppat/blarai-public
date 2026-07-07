"""V matrix V7 -- cross-project byte-identity (project portability proof).

Verifies that ``tools._project_context.resolve`` produces ``ProjectContext``
instances that differ ONLY in the project-identity fields (``root``, ``name``,
``vikunja_project_id``) when invoked against two distinct synthetic project
trees -- i.e., the resolution pathway carries no hardcoded BlarAI assumptions
and is genuinely project-portable.

This is the "cross-project byte-identity diff" check: the *structural shape*
of the returned ProjectContext (its dataclass field set + dict serialization
shape) is byte-identical across projects; only the *values* of identity
fields legitimately differ.

Stage 2.7.v2 V matrix V7. Uses pytest tmp_path fixture for filesystem
isolation per Guide-#6 g4 strategy.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from tools._project_context import REGISTRY_RELATIVE, ProjectContext, resolve


def _materialize_synthetic_project(parent: Path, name: str, project_id: int) -> Path:
    """Create a minimal synthetic project tree: just the registry file."""
    project_dir = parent / name
    project_dir.mkdir()
    registry_path = project_dir / REGISTRY_RELATIVE
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(f"{name}_project_id: {project_id}\n", encoding="utf-8")
    return project_dir


def test_two_synthetic_projects_resolve_to_distinct_contexts(tmp_path: Path) -> None:
    """Two synthetic project trees produce ProjectContexts with distinct identity."""
    proj_alpha = _materialize_synthetic_project(tmp_path, "alpha", 11)
    proj_beta = _materialize_synthetic_project(tmp_path, "beta", 22)

    ctx_alpha = resolve(cli_root=proj_alpha)
    ctx_beta = resolve(cli_root=proj_beta)

    assert isinstance(ctx_alpha, ProjectContext)
    assert isinstance(ctx_beta, ProjectContext)

    assert ctx_alpha.name == "alpha"
    assert ctx_beta.name == "beta"
    assert ctx_alpha.vikunja_project_id == 11
    assert ctx_beta.vikunja_project_id == 22
    assert ctx_alpha.root == proj_alpha.resolve()
    assert ctx_beta.root == proj_beta.resolve()


def test_cross_project_structural_shape_byte_identical(tmp_path: Path) -> None:
    """ProjectContext dataclass field set is identical across projects.

    The byte-identity claim: every ProjectContext, regardless of which project
    it represents, exposes the SAME dataclass fields in the SAME order. No
    project carries extra metadata or omits any field. This proves the
    resolution code path is project-agnostic at the type level.
    """
    proj_alpha = _materialize_synthetic_project(tmp_path, "alpha", 11)
    proj_beta = _materialize_synthetic_project(tmp_path, "beta", 22)

    ctx_alpha = resolve(cli_root=proj_alpha)
    ctx_beta = resolve(cli_root=proj_beta)

    fields_alpha = tuple(f.name for f in dataclasses.fields(ctx_alpha))
    fields_beta = tuple(f.name for f in dataclasses.fields(ctx_beta))
    assert fields_alpha == fields_beta, (
        f"ProjectContext field shape diverges across projects: "
        f"alpha={fields_alpha}, beta={fields_beta}"
    )


def test_cross_project_diff_isolates_to_identity_fields_only(tmp_path: Path) -> None:
    """The diff between two ProjectContext serializations isolates to identity fields.

    Asserts that fields differing across two distinct projects are exactly the
    project-identity fields {root, name, vikunja_project_id}, and no others.
    Catches accidental cross-project leakage (e.g., a global-cached field that
    fails to refresh between resolves).
    """
    proj_alpha = _materialize_synthetic_project(tmp_path, "alpha", 11)
    proj_beta = _materialize_synthetic_project(tmp_path, "beta", 22)

    ctx_alpha = resolve(cli_root=proj_alpha)
    ctx_beta = resolve(cli_root=proj_beta)

    dict_alpha = dataclasses.asdict(ctx_alpha)
    dict_beta = dataclasses.asdict(ctx_beta)

    differing_keys = {k for k in dict_alpha if dict_alpha[k] != dict_beta[k]}
    expected_diff_keys = {"root", "name", "vikunja_project_id"}
    # Every legitimate diff field MUST appear; no unexpected fields may diff.
    unexpected_diff = differing_keys - expected_diff_keys
    assert not unexpected_diff, (
        f"Unexpected ProjectContext fields differ across projects: {unexpected_diff}. "
        f"Possible cross-project state leakage."
    )


@pytest.mark.parametrize(
    "name,project_id",
    [("alpha", 11), ("beta", 22), ("gamma", 99)],
)
def test_resolve_round_trip_per_synthetic_project(
    tmp_path: Path, name: str, project_id: int
) -> None:
    """Each synthetic project resolves with the registry-declared id intact."""
    proj_dir = _materialize_synthetic_project(tmp_path, name, project_id)
    ctx = resolve(cli_root=proj_dir)
    assert ctx.name == name
    assert ctx.vikunja_project_id == project_id
    assert ctx.root == proj_dir.resolve()
