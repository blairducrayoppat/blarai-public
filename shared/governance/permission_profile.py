"""What BlarAI is allowed to do, in one readable statement (#1582).

Answering "what can it do right now?" used to mean reading a TOML file, a
risk-tier table, a rule engine and several runbooks, and knowing which of them
outranks which. That is a governance surface only its author can use, and its
author is not the one who owns the risk.

THIS IS NOT AN ADJUDICATOR, and the distinction is the whole design. It decides
nothing and enforces nothing. Every value below is READ from the surface that
owns it, at the moment you run it:

    capability on/off      the Assistant Orchestrator's own config file, resolved
                           by the service's own resolver for the running
                           deployment mode
    which hosts            DeterministicPolicyChecker._EGRESS_ALLOWLIST
    which tools go out     tools.is_egress_tool / tools._EGRESS_TOOLS
    the uncovered case     tools.risk_tier's own fallback, and the Layer-3 lock's
                           config flag

Nothing here restates a value. A profile that kept its own copy of the answer
would be a second source of truth about permissions, which is the failure it
exists to end — and a second thing to forget to update at a ceremony.

THE UNCOVERED CASE IS THE LOAD-BEARING PART, and what the code does is not what
a reader would guess. See :class:`UncoveredBehaviour`.

Usage::

    python -m shared.governance.permission_profile
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Capability",
    "UncoveredBehaviour",
    "Profile",
    "resolve",
    "render",
    "main",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Capability:
    """One thing BlarAI can or cannot do, and the switch that decides it."""

    name: str
    """Plain language, as the operator would say it."""

    section: str
    """The config section that decides it. Named so the answer is checkable."""

    enabled: bool

    present: bool
    """Whether this topology's settings file has the switch at all.

    Five of the six capabilities have no section in ``guest_runtime.toml``: the
    guest runs a subset. Refusing to run there was wrong twice over -- a raw
    traceback is not a governance statement, and "cannot state whether that
    capability is on" is not the honest answer when the honest answer is "that
    capability does not exist in this topology".

    Absent is NOT reported as off. That the HOST file carries all six is held by
    a gate test, which is where an accidentally deleted section should fail --
    not at the operator's terminal.
    """

    what_it_does: str

    leaves_the_machine: str | None
    """Which scope and which host, or None when nothing leaves."""


@dataclass(frozen=True)
class UncoveredBehaviour:
    """What happens to an action no rule covers - read, not assumed.

    THE COMFORTABLE ANSWER IS "it asks you", AND IT IS WRONG. An earlier version
    of this module printed a different wrong answer -- that such an action "goes
    to the Policy Agent, which decides using the model" -- and review showed the
    model is never consulted on a tool dispatch at all. ``_adjudicate_tool_dispatch``
    says so in its own docstring: "the PA's GPU classifier is not invoked here".
    ``DeterministicPolicyChecker.check`` returning ``None`` means no rule
    objected, and at that door no objection means EXECUTE.

    So the honest account has three branches, and the order matters because the
    first control to fire is not the one you would guess:

    1. A tool whose NAME is not on ``TOOL_CALL_ALLOWLIST`` is refused before any
       of this -- the loop breaks with "BlarAI does not provide that tool". That
       is the operative control for an unknown name, not the risk tier.
    2. A tool that IS callable but that nobody has given a risk tier falls back
       to DANGEROUS, and under untrusted content the Layer-3 lock refuses every
       non-SAFE tool with no override.
    3. That same tool, in a session with no untrusted content, RUNS. No rule
       mentions it, and no rule objecting is not the same as something approving.

    Branch 3 is why this class reports ``callable_but_unclassified``. The
    fallback exists for the day the callable set and the tiered set diverge; the
    rendered output states whether they have, rather than this docstring pinning
    a count that goes stale the moment a tool is added (it said "eight" while
    two more were being built).
    """

    unknown_tool_tier: str
    """``risk_tier``'s own fallback for a name it has never seen."""

    tier_is_locked_under_untrusted_content: bool
    """Whether that fallback tier is one the Layer-3 lock actually refuses.

    The lock's predicate is ``tier != SAFE``. Branching the operator-facing
    REFUSED paragraph on the config flag ALONE was a real defect: loosening the
    fallback to SAFE stopped the enforcement while the display kept its
    confident paragraph.
    """

    untrusted_content_lock_on: bool
    lock_flag: str

    callable_tools: tuple[str, ...]
    callable_but_unclassified: tuple[str, ...]


@dataclass(frozen=True)
class Profile:
    config_path: Path
    deployment_mode: str
    capabilities: tuple[Capability, ...]
    egress_hosts: tuple[str, ...]
    egress_tools: tuple[str, ...]
    egress_tools_live: tuple[str, ...]
    """The outbound tools whose governing capability is switched ON.

    Rendering the outbound section from ``egress_tools`` alone made the profile
    contradict itself: with [web_search].enabled false -- step 1 of the re-weld
    runbook -- one page said both "Search the web - switched off" and "web_search
    leaves this machine". The operator verifying a re-weld was told the thing
    they had just switched off still reaches the network.
    """

    uncovered: UncoveredBehaviour


# The capabilities this profile knows how to describe, and the config section
# that decides each. A section listed here MUST exist and MUST be read by the
# service — `test_every_capability_in_the_profile_is_really_enforced` holds that,
# because a profile naming a switch nothing reads is worse than no profile.
_CAPABILITIES: tuple[tuple[str, str, str, str | None], ...] = (
    (
        "knowledge",
        "Read your own documents",
        "Takes documents into a local knowledge bank and searches them when "
        "answering. The bank is on this machine and encrypted.",
        None,
    ),
    (
        "web_search",
        "Search the web",
        "Sends a search query out to the internet when answering. It also needs "
        "the sealed search key on this machine; without it the capability stays "
        "dormant whatever this switch says.",
        "egress",
    ),
    (
        "image_generation",
        "Make images",
        "Generates images locally on the graphics chip. Nothing is sent out.",
        None,
    ),
    (
        "organise_userdata",
        "Move files around inside your data folder",
        "Moves files matching a pattern into a folder you ALREADY HAVE - it "
        "does not create folders, and refuses a destination that is not "
        "there. Moves ONLY - "
        "it never deletes, copies or overwrites, and it refuses outright if "
        "something with the same name is already there rather than renaming "
        "yours. Everything stays inside your data folder. It always shows you "
        "HOW MANY files would move and asks first, and it needs the rehearsal "
        "switch on as well as this one.",
        None,
    ),
    (
        "curate_knowledge",
        "Erase documents from your knowledge bank",
        "Permanently erases saved documents matching what you describe - by "
        "source, by type, or by when they were taken in. THIS CANNOT BE UNDONE: "
        "the rows are overwritten, not just unlinked. It always shows you how "
        "many would go and asks before erasing any, and it needs the rehearsal "
        "switch on as well as this one. A request that names nothing matches "
        "nothing, never everything.",
        None,
    ),
    (
        "fleet_dispatch",
        "Run coding agents on your other projects",
        "Starts local coding processes against repositories you name. Local "
        "only; it cannot reach the network and it is refused on BlarAI's own "
        "repository.",
        None,
    ),
    (
        "coordinator",
        "Propose its own next steps",
        "Drafts proposals about its own work. Advisory only - it has no way to "
        "act on them, by construction.",
        None,
    ),
    (
        "simulate_first",
        "Rehearse an action before doing it",
        "Runs a dry run of an action first and shows you the result.",
        None,
    ),
)


# Which capability switch governs which outbound tool. Locked by
# `test_every_outbound_tool_is_governed_by_a_capability`: an outbound tool with
# no governing capability would leave the machine without appearing under any
# switch the operator can see.
_CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {"web_search": ("web_search",)}


def _assistant_orchestrator_config() -> tuple[Path, str]:
    """``(config path, deployment mode)`` the running service would use.

    Resolved with the service's OWN resolver rather than a hardcoded filename,
    so this reads the file the service reads. Host and guest topologies use
    different config files, and a profile that read the wrong one would report
    permissions nobody is running under.
    """
    from shared.runtime_config import (
        resolve_deployment_mode,
        resolve_service_config_path,
    )

    mode = resolve_deployment_mode()
    service_root = _REPO_ROOT / "services" / "assistant_orchestrator"
    return (
        resolve_service_config_path(service_root, deployment_mode=mode),
        mode.value,
    )


def resolve(config_path: Path | None = None) -> Profile:
    """Read every authority and assemble the profile. Decides nothing.

    ``config_path`` overrides which settings file is read. It exists so the
    regression locks can flip a real flag in a real TOML file and watch the
    displayed answer move -- a profile whose display cannot be shown to FOLLOW
    the setting is not resolved from the setting, it is a second copy of it,
    which is the failure this exists to end. Left None, it resolves the file the
    running service would use.
    """
    from services.assistant_orchestrator.src import tools
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker

    if config_path is None:
        config_path, mode = _assistant_orchestrator_config()
    else:
        config_path = Path(config_path)
        mode = "(the file you named)"
    with open(config_path, "rb") as handle:
        config = tomllib.load(handle)

    egress_hosts = tuple(sorted(DeterministicPolicyChecker._EGRESS_ALLOWLIST))
    egress_tools = tuple(sorted(tools._EGRESS_TOOLS))

    capabilities: list[Capability] = []
    for section, name, what, kind in _CAPABILITIES:
        block = config.get(section)
        present = isinstance(block, dict) and "enabled" in block
        leaves = None
        if kind == "egress":
            hosts = ", ".join(egress_hosts) if egress_hosts else "nothing"
            leaves = f"web search only, and only to: {hosts}"
        capabilities.append(
            Capability(
                name=name,
                section=section,
                enabled=bool(block["enabled"]) if present else False,
                present=present,
                what_it_does=what,
                leaves_the_machine=leaves,
            )
        )

    from services.assistant_orchestrator.src.pgov import TOOL_CALL_ALLOWLIST

    pgov = config.get("pgov", {})
    lock_on = bool(pgov.get("block_tools_on_untrusted_content", False))
    unknown_tier = tools.risk_tier("a-tool-name-that-has-never-existed")

    uncovered = UncoveredBehaviour(
        unknown_tool_tier=unknown_tier.value,
        # The lock's OWN predicate, not a restatement of it.
        tier_is_locked_under_untrusted_content=unknown_tier != tools.RiskTier.SAFE,
        untrusted_content_lock_on=lock_on,
        lock_flag="[pgov].block_tools_on_untrusted_content",
        callable_tools=tuple(sorted(TOOL_CALL_ALLOWLIST)),
        callable_but_unclassified=tuple(
            sorted(set(TOOL_CALL_ALLOWLIST) - set(tools._TOOL_RISK_TIER))
        ),
    )

    enabled_sections = {c.section for c in capabilities if c.enabled}
    live_outbound = tuple(
        sorted(
            tool
            for tool in egress_tools
            for section, governed in _CAPABILITY_TOOLS.items()
            if tool in governed and section in enabled_sections
        )
    )

    return Profile(
        config_path=config_path,
        deployment_mode=mode,
        capabilities=tuple(capabilities),
        egress_hosts=egress_hosts,
        egress_tools=egress_tools,
        egress_tools_live=live_outbound,
        uncovered=uncovered,
    )


def render(profile: Profile) -> str:
    """The operator-facing statement. Prose, not a table dump.

    ASCII only, deliberately. This is read in a Windows console, whose default
    code page renders an em dash as a replacement character -- so the one
    document meant to be read start to finish by a non-technical operator would
    have arrived peppered with mojibake.
    """
    on = [c for c in profile.capabilities if c.present and c.enabled]
    off = [c for c in profile.capabilities if c.present and not c.enabled]
    absent = [c for c in profile.capabilities if not c.present]

    lines: list[str] = []
    lines.append("WHAT BLARAI IS ALLOWED TO DO RIGHT NOW")
    lines.append("")
    lines.append(
        f"Read from {profile.config_path.name} ({profile.deployment_mode} mode) "
        "and from the code, just now. Nothing here is a stored copy."
    )
    lines.append("")

    lines.append(f"IT CAN ({len(on)}):")
    for cap in on:
        lines.append(f"  - {cap.name}")
        lines.append(f"      {cap.what_it_does}")
        if cap.leaves_the_machine:
            lines.append(f"      LEAVES THIS MACHINE: {cap.leaves_the_machine}")
    lines.append("")

    if off:
        lines.append(f"IT CANNOT ({len(off)}):")
        for cap in off:
            lines.append(f"  - {cap.name} - switched off")
            lines.append(f"      {cap.what_it_does}")
        lines.append("")

    if absent:
        lines.append(f"NOT PART OF THIS TOPOLOGY ({len(absent)}):")
        for cap in absent:
            lines.append(
                f"  - {cap.name} - no setting for it in "
                f"{profile.config_path.name}, so it does not run here at all."
            )
        lines.append("")

    lines.append("WHAT LEAVES THIS MACHINE:")
    if not profile.egress_tools_live:
        lines.append(
            "  Nothing. No capability that could reach the network is switched "
            "on here."
        )
    elif profile.egress_hosts:
        lines.append(
            f"  {', '.join(profile.egress_tools_live)} - and only to "
            f"{', '.join(profile.egress_hosts)}."
        )
        lines.append(
            "  Every other outbound address is refused by rule, whatever any "
            "setting says."
        )
    else:
        lines.append(
            f"  {', '.join(profile.egress_tools_live)} is switched on, but the "
            "list of permitted addresses is EMPTY, so every outbound attempt is "
            "refused."
        )
    lines.append("")

    lines.append("SOMETHING IT HAS NEVER BEEN TOLD ABOUT:")
    uncovered = profile.uncovered
    lines.append(
        f"  It can only call {len(uncovered.callable_tools)} named tools. "
        "Anything else it tries to call is refused by name, before any other "
        "check runs, and the answer you see is that BlarAI does not provide "
        "that tool."
    )
    if uncovered.callable_but_unclassified:
        lines.append(
            "  WARNING: these tools can be called and nobody has classified "
            f"them: {', '.join(uncovered.callable_but_unclassified)}."
        )
        lines.append(
            f"  They are treated as {uncovered.unknown_tool_tier}."
        )
        if uncovered.untrusted_content_lock_on and (
            uncovered.tier_is_locked_under_untrusted_content
        ):
            lines.append(
                "  In a conversation that has taken in outside content - a web "
                "result, a document you added - they are REFUSED outright, with "
                "no way to wave them through."
            )
            lines.append(
                "  In any other conversation they WOULD RUN. No rule mentions "
                "them, and no rule objecting is not the same as something "
                "approving. This is the case worth acting on."
            )
        else:
            lines.append(
                "  Nothing currently refuses them, in any conversation. "
                f"{uncovered.lock_flag} is "
                f"{'ON' if uncovered.untrusted_content_lock_on else 'OFF'} and "
                f"the fallback tier is {uncovered.unknown_tool_tier}."
            )
    else:
        lines.append(
            "  Every one of them has been classified, so there is nothing it "
            "can call that no rule covers."
        )
        lines.append(
            "  If an unclassified tool is ever added, it is treated as "
            f"{uncovered.unknown_tool_tier} - the most restricted setting, not "
            "the least."
            if uncovered.tier_is_locked_under_untrusted_content
            else "  WARNING: if an unclassified tool is ever added it is "
            f"treated as {uncovered.unknown_tool_tier}, which the "
            "outside-content lock does NOT refuse."
        )
        if uncovered.untrusted_content_lock_on and (
            uncovered.tier_is_locked_under_untrusted_content
        ):
            lines.append(
                "  In a conversation that has taken in outside content it would "
                "be REFUSED outright. In any other conversation it would RUN: "
                "the rules are written to catch known-bad actions, and an "
                "action no rule mentions draws no objection."
            )
        else:
            lines.append(
                f"  WARNING: {uncovered.lock_flag} is "
                f"{'ON' if uncovered.untrusted_content_lock_on else 'OFF'} and "
                f"the fallback tier is {uncovered.unknown_tool_tier}, so the "
                "backstop that would refuse such a tool is not in force."
            )
    lines.append("")

    lines.append(
        "This statement describes what the controls DO. It is not itself a "
        "control - it decides nothing and can permit nothing."
    )
    return "\n".join(lines) + "\n"


def main(argv: "list[str] | None" = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m shared.governance.permission_profile",
        description=(
            "Print what BlarAI is currently allowed to do, read from the live "
            "settings and code. Changes nothing."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Read a specific settings file instead of the running one.",
    )
    args = parser.parse_args(argv)
    sys.stdout.write(render(resolve(args.config)))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
