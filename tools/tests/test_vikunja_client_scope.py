"""Tests for tools/_vikunja_client.py (Stage 2.1 hard-rule wrapper).

The cleanup-C3 ``test_list_with_bool_project_id_raises`` MUST NOT be skipped or
weakened — it guards against ``bool`` (a subclass of ``int``) bypassing the
project-scope gate.
"""
import pytest

from tools._vikunja_client import ProjectScopeError, VikunjaClient


def test_list_without_project_id_raises():
    c = VikunjaClient("http://localhost:3456", "x")
    with pytest.raises(ProjectScopeError):
        c.list_tasks(project_id=None)


def test_list_with_string_project_id_raises():
    c = VikunjaClient("http://localhost:3456", "x")
    with pytest.raises(ProjectScopeError):
        c.list_tasks(project_id="1")


def test_list_with_bool_project_id_raises():
    """bool is a subclass of int; the gate must reject it explicitly (cleanup-C3)."""
    c = VikunjaClient("http://localhost:3456", "x")
    with pytest.raises(ProjectScopeError):
        c.list_tasks(project_id=True)
    with pytest.raises(ProjectScopeError):
        c.list_tasks(project_id=False)


def test_list_with_int_project_id_ok():
    c = VikunjaClient("http://localhost:3456", "x")
    # Should not raise. HTTP delegation is wired in Stage 2.6; today the
    # method returns None on a valid project_id, which is sufficient to
    # confirm the gate accepts a clean int.
    c.list_tasks(project_id=3)
    c.search_tasks(project_id=3, query="anything")


def test_require_project_id_returns_value_on_int():
    """Internal helper: returns the int unchanged on valid input."""
    from tools._vikunja_client import _require_project_id

    assert _require_project_id(7) == 7


def test_require_project_id_rejects_float():
    """Floats are not ints — must be rejected."""
    from tools._vikunja_client import _require_project_id

    with pytest.raises(ProjectScopeError):
        _require_project_id(3.0)


def test_require_project_id_rejects_zero():
    """Stage 2.4.v2 finding f1: project_id=0 is non-positive and bypasses Vikunja's
    server-side scope (returns 200 OK with data). The chokepoint must reject."""
    from tools._vikunja_client import _require_project_id

    with pytest.raises(ProjectScopeError):
        _require_project_id(0)


def test_require_project_id_rejects_negative():
    """Stage 2.4.v2 finding f1: any negative int is non-positive and bypasses Vikunja's
    server-side scope. The chokepoint must reject."""
    from tools._vikunja_client import _require_project_id

    with pytest.raises(ProjectScopeError):
        _require_project_id(-1)
    with pytest.raises(ProjectScopeError):
        _require_project_id(-99999)
