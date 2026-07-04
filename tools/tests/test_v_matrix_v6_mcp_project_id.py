"""V matrix V6 -- MCP server project_id rejection (mock-based).

Verifies that every ``@mcp.tool()`` handler in ``tools/vikunja_mcp/server.py``
that is gated on a ``project_id`` rejects bad values at handler entry by
raising ``ProjectScopeError`` BEFORE any HTTP call is issued. The rejection
chain runs through the chokepoint helper ``_require_project_id`` exported
from ``tools/_vikunja_client.py`` (D4 DIVERGE-APPROVED retention -- see
``server.py`` module docstring "Decision: KEEP all 8 ``_require_project_id``
call sites").

Bad-value matrix per chokepoint contract (see test_vikunja_client_scope.py):
    None, "1" (string), True/False (bool), 3.0 (float), 0, -1

The test invokes each handler with each bad value and asserts the chokepoint
fires. Because ``_require_project_id`` is the FIRST statement in each handler
body, the rejection happens before any ``_api_*`` HTTP delegation, so no HTTP
mocking is required.

Stage 2.7.v2 V matrix V6.
"""
from __future__ import annotations

import pytest

from tools._vikunja_client import ProjectScopeError
from tools.vikunja_mcp import server


# Handlers gated on a project_id parameter (empirically discovered via
# grep_search ``_require_project_id\(`` in tools/vikunja_mcp/server.py).
# ``project_summary`` is NOT included: it iterates ALL projects via /projects
# and does not gate on a single project_id.
GATED_HANDLERS = [
    "get_project",
    "update_project",
    "delete_project",
    "list_tasks",
    "create_task",
    "search_tasks",
    "bulk_create_tasks",
]

BAD_PROJECT_IDS = [None, "1", True, False, 3.0, 0, -1]


def _invoke_handler(handler_name: str, project_id):
    """Invoke a server handler with the given project_id, supplying minimum
    required other args. Returns whatever the handler returns; raises whatever
    the handler raises.
    """
    handler = getattr(server, handler_name)
    # FastMCP's @mcp.tool() may wrap the function in a Tool object; if so,
    # reach the underlying callable.
    if not callable(handler) and hasattr(handler, "fn"):
        handler = handler.fn

    if handler_name in ("get_project", "delete_project"):
        return handler(project_id=project_id)
    if handler_name == "update_project":
        return handler(project_id=project_id, title="x")
    if handler_name == "list_tasks":
        return handler(project_id=project_id)
    if handler_name == "create_task":
        return handler(project_id=project_id, title="x")
    if handler_name == "search_tasks":
        return handler(project_id=project_id, query="x")
    if handler_name == "bulk_create_tasks":
        return handler(project_id=project_id, tasks_json="[]")
    raise AssertionError(f"unhandled handler in test scaffold: {handler_name}")


@pytest.mark.parametrize("handler_name", GATED_HANDLERS)
@pytest.mark.parametrize("bad_value", BAD_PROJECT_IDS)
def test_handler_rejects_bad_project_id(handler_name: str, bad_value) -> None:
    """Each gated handler must raise ProjectScopeError on bad project_id at entry."""
    with pytest.raises(ProjectScopeError):
        _invoke_handler(handler_name, bad_value)


def test_gated_handlers_set_matches_require_project_id_call_sites() -> None:
    """Audit: the GATED_HANDLERS list must match the actual ``_require_project_id``
    invocations in server.py. Catches drift if a future maintainer adds a
    project_id-gated handler without updating this test fixture.
    """
    import inspect

    source = inspect.getsource(server)
    # Count `_require_project_id(project_id)` invocation lines (not the import,
    # not docstring references).
    invocation_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("_require_project_id(project_id)")
    ]
    assert len(invocation_lines) == len(GATED_HANDLERS), (
        f"GATED_HANDLERS ({len(GATED_HANDLERS)}) does not match "
        f"_require_project_id call sites ({len(invocation_lines)}) in server.py. "
        f"Update GATED_HANDLERS or investigate handler-coverage drift."
    )
