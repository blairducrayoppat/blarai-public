"""BlarAI → agentic-setup coding-fleet dispatch surface (UC headless-coding).

BlarAI does NOT embed a coder. It DISPATCHES to the existing fleet: enqueue a
task via the fleet's documented entry points, trigger a run, read the summary.
Local host subprocess only — no network egress. Dormant by default
(``[fleet_dispatch].enabled=false``). See ``shared/fleet/dispatch.py``.
"""
