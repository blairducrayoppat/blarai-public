"""#1152 — the IPC frame cap must AGREE across both ends of the AO channel.

THE INCIDENT (2026-07-28, LA-blocking, twice). A real operator `/dispatch` produced a
PLAN result of 65891 bytes, then 66938 bytes, against a 65536-byte cap. The plan
SUCCEEDED both times; the AO could not deliver it, `encode` raised, the serve loop
dropped the connection, and the operator saw "No response from the Assistant
Orchestrator" — which asserts the AO went SILENT about work it had actually finished.
An entire diagnostic arc, and one merged fix, went to the wrong cause (a timeout) on
the strength of that message plus a reproduction that happened to generate one fewer
task and fit.

WHY THIS FILE EXISTS, AND WHY A CONFIG KNOB WAS NOT ENOUGH.
`[ipc].max_message_bytes` was ALREADY config-raisable (validated 1 KB .. 1 MB) and
ADR-031 described it as such. Raising it alone would have changed NOTHING, for two
independent reasons, each invisible from the config file:

  1. The AO built its `MessageFramer()` in ``__init__`` with no argument — before any
     config is read — so the FRAMER kept the compiled-in 64 KB default forever while
     the TRANSPORT honored the configured value. The framer is the binding cap on
     encode, and it is the one that raised.
  2. The gateway never set a cap at all, on any of its `VsockConfig` sites. So even a
     correctly-raised AO would have encoded a frame the gateway then refused on
     receive (`length > max_message_bytes` -> `None`) — reproducing the identical
     "No response" it was meant to cure.

Both are AGREEMENT defects: two ends of one channel, each individually defensible,
disagreeing. That is the shape `tests/security/test_timeout_ordering.py` was written
for in #1122 (an outer bound below an inner one), recurring on a different axis five
days later. So, as there: assert the RELATIONSHIP, not the values. Every number here
may be retuned freely; what may never happen again is the two ends disagreeing, or a
configured cap that no live consumer reads.

SCOPE — this is a PER-CHANNEL raise, not the transport-wide loosening ADR-031
rejected. `VsockConfig.max_message_bytes` and `DEFAULT_MAX_MESSAGE_BYTES` keep their
64 KB defaults, so the guest-VM parse boundary (hostile fetched HTML, ADR-030) is
untouched; only the loopback+mTLS host channel carrying BlarAI's own bounded planning
metadata is widened, and only because the launcher explicitly threads it.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from shared.ipc.protocol import DEFAULT_MAX_MESSAGE_BYTES
from shared.ipc.vsock import VsockAddress, VsockConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AO_CONFIG = (
    _REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"
)
_GATEWAY_SRC = _REPO_ROOT / "services" / "ui_gateway" / "src" / "transport.py"
_AO_SRC = _REPO_ROOT / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"

#: The validator's accepted band for `[ipc].max_message_bytes`
#: (`AO_CFG_MAX_MESSAGE_BYTES_INVALID`). Mirrored, not imported, because the
#: validation call site is inside a long resolve function.
_CONFIG_MIN, _CONFIG_MAX = 1024, 1_048_576


def _configured_cap() -> int:
    with _AO_CONFIG.open("rb") as fh:
        return int(tomllib.load(fh)["ipc"]["max_message_bytes"])


# ---- the configured value is real and in-band -----------------------------


def test_configured_cap_is_within_the_validated_band() -> None:
    """A cap the AO's own config validator would reject cannot ship."""
    cap = _configured_cap()
    assert _CONFIG_MIN <= cap <= _CONFIG_MAX, (
        f"[ipc].max_message_bytes={cap} is outside the validated "
        f"{_CONFIG_MIN}..{_CONFIG_MAX} band — the AO would refuse to start."
    )


def test_configured_cap_clears_the_observed_worst_case() -> None:
    """The two live 2026-07-28 failures are the floor this must stay above.

    Pinned as a MEASUREMENT, not a preference: 66938 bytes is a real PLAN result for a
    real operator goal. A future shrink below it silently re-opens the incident.
    """
    assert _configured_cap() > 66_938, (
        "the configured frame cap must exceed the largest PLAN result actually "
        "observed in production (66938 bytes, 2026-07-28) — with headroom, since "
        "payload size grows O(n_tasks x (goal + requirements))"
    )


# ---- the defaults stay conservative (no transport-wide widening) ----------


def test_the_compiled_in_defaults_are_unchanged() -> None:
    """ADR-031's actual concern: do not loosen the cap for every channel at once.

    The raise is delivered by the launcher threading a value, never by moving the
    default out from under the guest-VM boundary and every other transport user.
    """
    assert DEFAULT_MAX_MESSAGE_BYTES == 65_536, (
        "the protocol default must stay 64 KB — raising it widens EVERY channel, "
        "including the guest parse boundary that handles hostile fetched HTML "
        "(ADR-030). #1152 is a per-channel raise; keep it that way."
    )
    probe = VsockConfig(address=VsockAddress(cid=0, port=1))
    assert probe.max_message_bytes == DEFAULT_MAX_MESSAGE_BYTES, (
        "VsockConfig's default must track the protocol default — two defaults that "
        "drift apart is the same agreement defect one layer down."
    )


def test_gateway_defaults_to_the_conservative_cap() -> None:
    """An un-threaded gateway must not silently inherit a wide cap."""
    src = _GATEWAY_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            names = [a.arg for a in node.args.kwonlyargs]
            if "max_message_bytes" not in names:
                continue
            default = node.args.kw_defaults[names.index("max_message_bytes")]
            assert isinstance(default, ast.Name) and (
                default.id == "DEFAULT_MAX_MESSAGE_BYTES"
            ), (
                "TransportGateway's max_message_bytes default must be "
                "DEFAULT_MAX_MESSAGE_BYTES (fail-safe/narrow), not a literal"
            )
            return
    raise AssertionError(
        "TransportGateway.__init__ no longer takes max_message_bytes — the gateway "
        "end of the agreement is gone; re-anchor this test rather than deleting it."
    )


# ---- REACHABILITY: a cap nothing reads is not a cap -----------------------


def test_every_gateway_vsock_config_carries_the_cap() -> None:
    """The #1152 gateway defect exactly: a `VsockConfig` built without the cap.

    Reachability, not definition (the built-but-wired-into-nothing class): a correctly
    threaded constructor argument is worth nothing if one connect path forgets to pass
    it — that path silently reverts to 64 KB and refuses the AO's larger frame.

    Hardened at independent review: the first draft matched only the bare
    ``VsockConfig(...)`` name form, and the reviewer demonstrated that both
    ``vsock.VsockConfig(...)`` (attribute) and ``VsockConfig as VC; VC(...)`` (alias)
    slipped past it. It also scanned one file. Both are now covered, across the whole
    gateway package — an evadable reachability lock invites the evasion.
    """
    missing: list[str] = []
    for path in sorted((_REPO_ROOT / "services" / "ui_gateway" / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Resolve local aliases: `from shared.ipc import VsockConfig as VC`.
        aliases = {"VsockConfig"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "VsockConfig" and a.asname:
                        aliases.add(a.asname)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (
                fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute)
                else ""
            )
            if name not in aliases:
                continue
            if "max_message_bytes" not in {kw.arg for kw in node.keywords}:
                missing.append(f"{path.name}:{node.lineno}")
    assert not missing, (
        f"VsockConfig built WITHOUT max_message_bytes at {missing}. That connect path "
        "keeps the 64 KB default and will refuse a larger frame the AO legitimately "
        "sent — the #1152 failure, which surfaces to the operator as 'No response "
        "from the Assistant Orchestrator'."
    )


def test_ao_binds_its_framer_to_the_resolved_config() -> None:
    """The other half: the AO's framer must use the CONFIGURED cap, not the default.

    Source-level because the binding happens during service start (listener bring-up),
    which a unit test cannot reach without a GPU and a real listener. The framer is the
    cap that actually raises on encode, so a framer left at the compiled-in default
    makes the whole config knob inert — which is precisely what it was.

    Hardened at independent review: a raw substring match would still pass if the
    rebind moved AFTER `listener.start()`, into an unreachable branch, or into a
    comment — the built-but-wired-into-nothing class this very file invokes. So the
    ORDER is asserted: the rebind must precede the listener that serves with it.
    """
    src = _AO_SRC.read_text(encoding="utf-8")
    assert "MessageFramer(resolved.vsock_config.max_message_bytes)" in src, (
        "the AO must rebuild its framer from the resolved [ipc].max_message_bytes "
        "once config is available. Built in __init__ with no argument, it keeps the "
        "64 KB compiled-in default forever and the config knob does nothing (#1152)."
    )
    tree = ast.parse(src)
    rebind_lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "MessageFramer"
        and any(
            isinstance(a, ast.Attribute) and a.attr == "max_message_bytes"
            for a in node.args
        )
    ]
    listener_lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "VsockListener"
    ]
    assert rebind_lines and listener_lines, (
        "could not locate both the framer rebind and the VsockListener construction — "
        "re-anchor this test rather than deleting it."
    )
    assert min(rebind_lines) < min(listener_lines), (
        f"the framer rebind (line {min(rebind_lines)}) must happen BEFORE the listener "
        f"is built (line {min(listener_lines)}) — a rebind after the AO starts serving "
        "leaves early requests encoding against the 64 KB default (#1152)."
    )


def test_launcher_threads_the_ao_LIVE_cap_into_the_gateway() -> None:
    """Both ends agree because ONE value feeds both — and it is the AO's LIVE value.

    Strengthened at independent review: an earlier draft re-parsed `default.toml` a
    SECOND time in the launcher. That reads the same file, so it usually agrees — but
    "usually agrees" is the defect class, not the fix: its fail-soft path returned
    64 KB while the AO ran at 256 KB, silently re-creating the one-sided cap on the
    quiet side (the operator would see the same generic "No response", with only a
    warning in the log). The cap must come from the AO object that is already started,
    so there is exactly ONE read and nothing to drift.
    """
    launcher_src = (_REPO_ROOT / "launcher" / "__main__.py").read_text(encoding="utf-8")
    assert "max_message_bytes=_gateway_frame_cap(_orchestrator_service)" in launcher_src, (
        "the launcher must thread the AO's LIVE resolved cap into TransportGateway"
    )
    assert "resolved_max_message_bytes" in launcher_src, (
        "the cap must come from the AO's resolved config property, not a second parse"
    )
    # The second-read must not come back: a re-parse is the drift this test exists for.
    assert "def _resolve_max_message_bytes(" not in launcher_src, (
        "the launcher must NOT re-parse default.toml for this value — two independent "
        "reads of one setting is the disagreement-between-ends defect itself (#1152)."
    )
    # Fail-closed, not fail-soft: guessing a cap re-opens the failure silently.
    assert "raise RuntimeError(" in launcher_src.split("def _gateway_frame_cap(")[1].split(
        "\ndef "
    )[0], (
        "_gateway_frame_cap must FAIL CLOSED when the AO has no resolved cap — a "
        "fallback here is indistinguishable from the bug (#1152)."
    )


def test_ao_exposes_its_live_cap_for_the_gateway() -> None:
    """The AO end of that single read must exist and report the SERVING value."""
    src = _AO_SRC.read_text(encoding="utf-8")
    assert "def resolved_max_message_bytes(" in src, (
        "AssistantOrchestratorService must expose the cap it is actually serving with"
    )
    assert "cfg.vsock_config.max_message_bytes" in src, (
        "the property must report the RESOLVED vsock config's cap — the same object "
        "the listener and framer were built from, not a re-read or a constant"
    )
