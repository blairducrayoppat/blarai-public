"""#1582: one readable statement of what BlarAI is currently allowed to do.

THE TICKET'S OWN WARNING IS THE FIRST TEST HERE: "If building it reveals that
the displayed answer and the enforced answer can differ, that divergence is the
real finding and outranks the display." So these locks are mostly not about the
prose. They are about whether the prose FOLLOWS the thing it describes.

A profile that printed a stored copy of the answer would pass any test that only
read its output. Every capability test below therefore flips a real flag in a
real settings file and watches the displayed answer move.

WHAT THIS PROFILE IS NOT: an adjudicator. It decides nothing and permits
nothing, and `test_the_profile_makes_no_decisions` holds that structurally --
principle 5 is one Policy-Agent door, and a second thing that answered
permission questions would be the side door the architecture forbids.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from shared.governance.permission_profile import (
    Profile,
    main,
    render,
    resolve,
)

_REPO = Path(__file__).resolve().parents[2]
_AO_CONFIG_DIR = _REPO / "services" / "assistant_orchestrator" / "config"
_AO_ENTRYPOINT = _REPO / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"

# [service] is name/version/log_level -- descriptive metadata, no permission
# claim and no number anything enforces. It is PINNED here rather than ignored:
# the point of this set is that a NEW unread section fails the test. See #1601.
_KNOWN_UNREAD_SECTIONS = {"service"}

# The names the AO entrypoint binds its parsed config to. The orphan detector
# only counts a section as READ when the access is anchored on one of these --
# see _sections_read_by_the_entrypoint for what happened without the anchor.
_CONFIG_OBJECT_NAMES = {"config_data"}


def _config_with(tmp_path: Path, **overrides: bool) -> Path:
    """A real copy of the live settings file with some flags flipped."""
    source = (_AO_CONFIG_DIR / "default.toml").read_text(encoding="utf-8")
    out = tmp_path / "default.toml"
    lines = source.splitlines()
    section = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
        elif section in overrides and stripped.startswith("enabled"):
            lines[i] = f"enabled = {str(overrides[section]).lower()}"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# The display must FOLLOW the setting. Everything else is decoration.
# ---------------------------------------------------------------------------


def test_turning_a_capability_off_changes_what_the_profile_says(
    tmp_path: Path,
) -> None:
    """THE TOGGLE, and the reason it leads this file.

    A profile holding its own copy of the answer would print the same thing
    here, and every other test in this file would still pass.
    """
    on_dir = tmp_path / "on"
    off_dir = tmp_path / "off"
    on_dir.mkdir()
    off_dir.mkdir()
    on = resolve(_config_with(on_dir, image_generation=True))
    off = resolve(_config_with(off_dir, image_generation=False))

    def _named(profile: Profile, section: str) -> bool:
        return next(c.enabled for c in profile.capabilities if c.section == section)

    assert _named(on, "image_generation") is True
    assert _named(off, "image_generation") is False, (
        "the settings file says the capability is off and the profile still "
        "reports it on -- the display is not resolved from the setting"
    )
    assert "Make images" in render(on).split("IT CANNOT")[0]
    assert "Make images" in render(off).split("IT CANNOT")[1]


def test_every_capability_the_profile_names_has_a_switch_in_the_config() -> None:
    """A capability named here whose switch does not exist would be a claim
    about a control that is not there."""
    config = tomllib.load((_AO_CONFIG_DIR / "default.toml").open("rb"))
    for capability in resolve().capabilities:
        block = config.get(capability.section)
        assert isinstance(block, dict) and "enabled" in block, (
            f"the profile reports '{capability.name}' from [{capability.section}], "
            "which has no 'enabled' switch in the settings file"
        )


def test_the_host_settings_file_carries_every_capability_switch() -> None:
    """An accidentally deleted capability section must fail HERE, in the gate,
    not at the operator's terminal.

    The first version raised at runtime instead, which crashed the command
    outright under guest topology -- where five of the six sections legitimately
    do not exist. A raw traceback is not a governance statement, and "cannot
    state whether that capability is on" is not the honest answer when the
    honest answer is "that capability does not exist in this topology".
    """
    config = tomllib.load((_AO_CONFIG_DIR / "default.toml").open("rb"))
    for capability in resolve().capabilities:
        block = config.get(capability.section)
        assert isinstance(block, dict) and "enabled" in block, (
            f"[{capability.section}].enabled has gone from the host settings "
            f"file, so the profile can no longer state whether "
            f"'{capability.name}' is on."
        )


def test_a_capability_absent_from_this_topology_is_not_reported_as_off(
    tmp_path: Path,
) -> None:
    """Absent and off are different facts, and reporting the first as the second
    is a reassurance derived from a missing section."""
    source = (_AO_CONFIG_DIR / "default.toml").read_text(encoding="utf-8")
    stripped = tmp_path / "default.toml"
    stripped.write_text(
        source.replace("[image_generation]", "[image_generation_gone]", 1),
        encoding="utf-8",
    )

    profile = resolve(stripped)
    capability = next(
        c for c in profile.capabilities if c.section == "image_generation"
    )
    assert capability.present is False
    assert capability.enabled is False

    text = render(profile)
    assert "NOT PART OF THIS TOPOLOGY" in text
    assert "Make images" in text.split("NOT PART OF THIS TOPOLOGY")[1]
    assert "Make images" not in text.split("IT CAN")[1].split("NOT PART")[0]


def test_the_command_runs_under_guest_topology(monkeypatch, capsys) -> None:
    """MEASURED: it raised KeyError under guest, because five of the six
    capability sections do not exist in guest_runtime.toml."""
    monkeypatch.setenv("BLARAI_RUNTIME_MODE", "guest")

    assert main([]) == 0
    text = capsys.readouterr().out
    assert "guest_runtime.toml" in text
    assert "NOT PART OF THIS TOPOLOGY" in text


# ---------------------------------------------------------------------------
# Egress: which scope, which host -- read from the enforcing surface.
# ---------------------------------------------------------------------------


def test_the_hosts_come_from_the_enforcing_allowlist_not_a_copy() -> None:
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker

    profile = resolve()
    assert set(profile.egress_hosts) == set(
        DeterministicPolicyChecker._EGRESS_ALLOWLIST
    ), (
        "the profile's host list and the list that actually refuses connections "
        "have drifted apart. The operator is reading a second copy."
    )
    assert profile.egress_hosts, "an empty host list would be reported as 'nothing'"


def test_the_egress_tools_come_from_the_tool_module() -> None:
    from services.assistant_orchestrator.src import tools

    assert set(resolve().egress_tools) == set(tools._EGRESS_TOOLS)


def test_switching_off_the_web_capability_removes_it_from_what_leaves(
    tmp_path: Path,
) -> None:
    """Review blocker 3, reproduced: with [web_search].enabled false -- step 1
    of the re-weld runbook -- one page said BOTH "Search the web - switched off"
    AND "web_search leaves this machine".

    The operator verifying a re-weld was told the thing they had just switched
    off still reaches the network. The outbound section was rendered from the
    tool set alone, independent of the capability flags, and the earlier toggle
    test used image_generation -- a non-egress capability -- so the interaction
    was never exercised.
    """
    source = (_AO_CONFIG_DIR / "default.toml").read_text(encoding="utf-8")
    welded = tmp_path / "default.toml"
    lines, section = source.splitlines(), None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
        elif section == "web_search" and stripped.startswith("enabled"):
            lines[i] = "enabled = false"
    welded.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")

    profile = resolve(welded)
    assert profile.egress_tools_live == (), (
        "web_search is switched off and the profile still lists it as live "
        "outbound traffic"
    )

    text = render(profile)
    outbound = text.split("WHAT LEAVES THIS MACHINE:")[1]
    assert "web_search" not in outbound, (
        "the re-weld page contradicts itself: " + outbound
    )
    assert "Nothing." in outbound


def test_every_outbound_tool_is_governed_by_a_capability_switch() -> None:
    """An outbound tool with no governing capability would leave the machine
    without appearing under any switch the operator can see -- so switching
    everything off would still show it as live."""
    from shared.governance.permission_profile import _CAPABILITY_TOOLS

    governed = {tool for tools_ in _CAPABILITY_TOOLS.values() for tool in tools_}
    ungoverned = set(resolve().egress_tools) - governed
    assert not ungoverned, (
        f"these tools reach the network under no capability switch: "
        f"{sorted(ungoverned)}"
    )


def test_the_profile_names_the_host_in_its_output() -> None:
    """The ticket asks for scope AND host for anything that leaves."""
    text = render(resolve())
    for host in resolve().egress_hosts:
        assert host in text, f"{host} is permitted but not named in the profile"
    assert "LEAVES THIS MACHINE" in text


# ---------------------------------------------------------------------------
# The uncovered case -- the load-bearing part.
# ---------------------------------------------------------------------------


def test_an_unclassified_tool_is_treated_as_the_most_restricted_tier() -> None:
    """Deny-by-default where it matters: the tool nobody has classified yet.

    Read from ``risk_tier``'s own fallback rather than asserted, so this fails
    if that default is ever loosened.
    """
    from services.assistant_orchestrator.src import tools

    assert resolve().uncovered.unknown_tool_tier == tools.RiskTier.DANGEROUS.value
    assert (
        tools.risk_tier("a-tool-that-has-never-existed") is tools.RiskTier.DANGEROUS
    ), "an unknown tool is no longer DANGEROUS by default"


def test_the_profile_never_claims_a_model_judges_an_uncovered_action() -> None:
    """Review blocker 1, reproduced: the first version told the operator that an
    action no rule covers "goes to the Policy Agent, which decides using the
    model". The model is NEVER consulted on a tool dispatch.

    ``_adjudicate_tool_dispatch`` says so in its own docstring -- "the PA's GPU
    classifier is not invoked here" -- and ``DeterministicPolicyChecker.check``
    returning None means no rule objected, which at that door means EXECUTE.
    The comfortable sentence was wrong in the reassuring direction, which is the
    one direction an operator-facing governance statement must never be wrong
    in.
    """
    text = render(resolve())

    for reassurance in ("using the model", "decides using", "judged locally",
                        "automatic question to you"):
        assert reassurance not in text, (
            f"the profile still tells the operator {reassurance!r}, which the "
            "tool-dispatch door does not do"
        )
    assert "no rule objecting is not the same as something approving" in text or (
        "draws no objection" in text
    ), "the profile does not state what actually happens when no rule matches"


def test_the_profile_says_an_unclassified_tool_WOULD_RUN() -> None:
    """The uncomfortable half of the truth, which is the half worth printing.

    Outside an untrusted-content session there is nothing that refuses a
    callable-but-unclassified tool. Saying so is the whole value of the section:
    it is the case an operator could act on.
    """
    text = render(resolve())
    assert "would RUN" in text or "WOULD RUN" in text, (
        "the profile does not tell the operator that an unclassified tool runs "
        "in a conversation with no outside content"
    )


def test_the_refusal_claim_follows_the_TIER_not_just_the_config_flag() -> None:
    """Review blocker 2, reproduced: the REFUSED paragraph branched on the
    config flag alone.

    The Layer-3 lock's own predicate is ``tier != SAFE``. Loosening the unknown
    tool fallback to SAFE stops the enforcement, and the display kept printing
    its confident REFUSED paragraph -- a stored editorial claim welded to a
    resolved value, reassuring about the exact loosening it should have flagged.
    """
    from services.assistant_orchestrator.src import tools

    profile = resolve()
    assert profile.uncovered.tier_is_locked_under_untrusted_content is (
        tools.risk_tier("never-existed") != tools.RiskTier.SAFE
    ), "the display's refusal condition is not the lock's own predicate"
    assert profile.uncovered.tier_is_locked_under_untrusted_content is True
    assert "REFUSED outright" in render(profile)


def test_a_SAFE_fallback_tier_removes_the_refusal_claim(monkeypatch) -> None:
    """The toggle for the test above, driven through the real predicate."""
    from services.assistant_orchestrator.src import tools

    monkeypatch.setattr(
        tools, "risk_tier", lambda name: tools._TOOL_RISK_TIER.get(name, tools.RiskTier.SAFE)
    )
    profile = resolve()
    assert profile.uncovered.tier_is_locked_under_untrusted_content is False

    text = render(profile)
    assert "REFUSED outright" not in text, (
        "the profile claims unclassified actions are refused while the tier it "
        "is holding is one the lock does not refuse"
    )
    assert "WARNING" in text


def test_the_backstop_being_off_is_reported_as_a_warning(tmp_path: Path) -> None:
    """The toggle for the test above: if the Layer-3 lock is switched off, the
    profile must say so rather than printing the same confident paragraph."""
    source = (_AO_CONFIG_DIR / "default.toml").read_text(encoding="utf-8")
    off = tmp_path / "default.toml"
    off.write_text(
        source.replace(
            "block_tools_on_untrusted_content = true",
            "block_tools_on_untrusted_content = false",
            1,
        ),
        encoding="utf-8",
    )

    profile = resolve(off)
    assert profile.uncovered.untrusted_content_lock_on is False
    text = render(profile)
    assert "WARNING" in text
    assert "REFUSED outright" not in text, (
        "the profile claims unclassified actions are refused while the control "
        "that refuses them is switched off"
    )


# ---------------------------------------------------------------------------
# Structural: not an adjudicator, and no orphaned settings.
# ---------------------------------------------------------------------------


def test_the_profile_makes_no_decisions() -> None:
    """Principle 5: ONE Policy-Agent door. A second thing that answered
    permission questions would be the side door the architecture forbids.

    By syntax tree: the module must not call any of the deciding functions. It
    reads ``_EGRESS_ALLOWLIST`` (a value) and ``risk_tier`` (a classification of
    a name, with no action attached); it must never call ``check``,
    ``adjudicate``, ``is_egress_allowed`` or anything that returns a verdict.
    """
    import shared.governance.permission_profile as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    # Review finding 8: the first version named `is_egress_allowed`, which does
    # not exist anywhere in the tree, and covered NONE of the functions that
    # actually decide or register a decider. A forbidden name for a function
    # that does not exist pads the set without adding coverage.
    FORBIDDEN = {
        # deciders
        "check",
        "adjudicate",
        "adjudicate_car",
        "_is_allowlisted_egress",
        "fetch_external",
        "fetch_external_binary",
        "execute",
        "validate_output",
        "request_escalation_consent",
        # registering a decider mutates the single adjudicator slot, which is
        # the precise principle-5 violation this test claims to hold
        "register_url_adjudicator",
        "clear_url_adjudicator",
    }
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else
        (node.func.id if isinstance(node.func, ast.Name) else "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    # The set must name functions that EXIST, or it certifies nothing.
    import services.assistant_orchestrator.src.tools as _tools_mod
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker

    assert hasattr(DeterministicPolicyChecker, "check")
    assert hasattr(DeterministicPolicyChecker, "_is_allowlisted_egress")
    assert hasattr(_tools_mod, "execute")

    assert not (called & FORBIDDEN), (
        "the profile calls a deciding function "
        f"({sorted(called & FORBIDDEN)}). It displays what the controls decide; "
        "it must never decide anything itself."
    )


def _sections_read_by_the_entrypoint() -> set[str]:
    """Config section names the AO entrypoint reads FROM THE CONFIG OBJECT.

    Two shapes, both anchored on the receiver being the config mapping itself:
    ``config_data.get("section")`` / ``config_data["section"]`` and
    ``require_section_dict(config_data, "section")``.

    THE ANCHOR IS THE POINT. An earlier version collected every string subscript
    and every ``.get(str)`` first argument anywhere in a 7,500-line file, on any
    object at all -- 164 strings, most of them JSON payload keys like "body",
    "filename", "decision", "height". Review planted a section called
    ``[decision]`` in the settings file and the orphan test PASSED, because a
    JSON key of that name appears somewhere in the entrypoint. A detector that
    can be satisfied by an unrelated string gives a false ALL-CLEAR, which is
    the one direction an orphan detector must never fail in.

    An earlier version also missed ``require_section_dict`` entirely and
    reported the live ``[runtime]`` section as an orphan -- the opposite error,
    and the one that gets a live section deleted.
    """
    tree = ast.parse(_AO_ENTRYPOINT.read_text(encoding="utf-8"))
    read: set[str] = set()

    def _is_config_object(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id in _CONFIG_OBJECT_NAMES

    for node in ast.walk(tree):
        # config_data["section"]
        if (
            isinstance(node, ast.Subscript)
            and _is_config_object(node.value)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            read.add(node.slice.value)
        if not isinstance(node, ast.Call):
            continue
        # config_data.get("section")
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _is_config_object(node.func.value)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            read.add(node.args[0].value)
        # require_section_dict(config_data, "section", ...)
        name = (
            node.func.attr if isinstance(node.func, ast.Attribute)
            else node.func.id if isinstance(node.func, ast.Name)
            else ""
        )
        if (
            name.startswith("require_section")
            and len(node.args) >= 2
            and _is_config_object(node.args[0])
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            read.add(node.args[1].value)
    return read


@pytest.mark.parametrize("config_name", ["default.toml", "guest_runtime.toml"])
def test_no_settings_section_is_read_by_nothing(config_name: str) -> None:
    """A settings file the operator reads is a governance surface.

    MEASURED 2026-09-20: ``[circuit_breaker]`` and ``[preemption]`` were read by
    nothing, and ``[circuit_breaker].max_tool_call_depth`` said 5 while the loop
    enforced 3 -- a number in the operator's own settings file that was wrong in
    the reassuring direction and that nothing would ever have corrected, because
    nothing read it. Both sections are gone.

    This pins the remainder so the next orphan fails here instead of being read
    as a setting.
    """
    config = tomllib.load((_AO_CONFIG_DIR / config_name).open("rb"))
    sections = {key for key, value in config.items() if isinstance(value, dict)}
    unread = sections - _sections_read_by_the_entrypoint()

    assert unread <= _KNOWN_UNREAD_SECTIONS, (
        f"{config_name} has settings nothing reads: {sorted(unread - _KNOWN_UNREAD_SECTIONS)}. "
        "A number in the settings file that nothing enforces is a false "
        "statement about what the system will do."
    )


def test_the_orphan_detector_is_wrong_in_NEITHER_direction() -> None:
    """The vacuity control, both ways -- and the second way is the one that bit.

    UNDER-collection makes the detector report a live section as an orphan, and
    someone deletes it. That happened: the first version missed
    ``require_section_dict`` and flagged ``[runtime]``, which carries the
    deployment mode.

    OVER-collection makes it report an orphan as read, which is a false
    all-clear and the direction that matters more. That happened too: the
    detector collected every string subscript anywhere in the file, so review
    planted a section named ``[decision]`` -- a JSON payload key that appears in
    the entrypoint -- and the orphan test passed over it.
    """
    read = _sections_read_by_the_entrypoint()

    # Under-collection: sections known to be live must be seen, and by BOTH
    # access shapes -- [runtime] via require_section_dict, the rest via .get().
    for live in ("runtime", "generation", "knowledge", "web_search", "pgov"):
        assert live in read, (
            f"the detector does not see [{live}], which the entrypoint demonstrably "
            "reads. It would report a live section as an orphan."
        )

    # Over-collection: strings that appear in the entrypoint as JSON/payload keys
    # must NOT be counted as config sections. These are review's planted case.
    entrypoint_source = _AO_ENTRYPOINT.read_text(encoding="utf-8")
    for payload_key in ("decision", "filename", "body", "height"):
        assert f'"{payload_key}"' in entrypoint_source, (
            f"this control assumes {payload_key!r} appears in the entrypoint as a "
            "non-config string; it no longer does, so pick another"
        )
        assert payload_key not in read, (
            f"the detector counts the payload key {payload_key!r} as a config "
            "section that is read. A settings section of that name would be "
            "waved through as healthy."
        )


def test_a_planted_orphan_section_is_actually_caught(tmp_path: Path) -> None:
    """Drive the real assertion over a settings file with an orphan in it.

    Reproduces review's exact planted case rather than trusting the detector's
    output shape.
    """
    config = tomllib.load((_AO_CONFIG_DIR / "default.toml").open("rb"))
    sections = {key for key, value in config.items() if isinstance(value, dict)}
    read = _sections_read_by_the_entrypoint()

    assert sections - read <= _KNOWN_UNREAD_SECTIONS  # the real tree is clean

    planted = sections | {"decision"}
    assert not (planted - read <= _KNOWN_UNREAD_SECTIONS), (
        "a planted [decision] section passes the orphan check -- the detector "
        "is satisfied by an unrelated string of the same name"
    )


def test_the_dead_caps_are_gone_from_both_settings_files() -> None:
    """The specific regression: the number that said 5 where the loop enforced 3."""
    from shared.constants import MAX_TOOL_CALL_DEPTH

    for name in ("default.toml", "guest_runtime.toml"):
        config = tomllib.load((_AO_CONFIG_DIR / name).open("rb"))
        assert "circuit_breaker" not in config, (
            f"{name} carries a [circuit_breaker] section again. Its "
            f"max_tool_call_depth said 5; the loop enforces {MAX_TOOL_CALL_DEPTH}."
        )
        assert "preemption" not in config, f"{name} carries [preemption] again"


def test_the_command_runs_and_says_nothing_it_cannot_support(capsys) -> None:
    assert main([]) == 0
    text = capsys.readouterr().out
    assert text.startswith("WHAT BLARAI IS ALLOWED TO DO RIGHT NOW")
    assert "decides nothing and can permit nothing" in text


def test_the_operator_facing_output_is_plain_ASCII() -> None:
    """It is read in a Windows console, whose default code page turns an em dash
    into a replacement character. MEASURED: the first version arrived peppered
    with them."""
    text = render(resolve())
    offenders = sorted({character for character in text if ord(character) > 127})
    assert not offenders, (
        f"non-ASCII in the operator-facing output: {offenders}. In a Windows "
        "console these arrive as replacement characters."
    )
