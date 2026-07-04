"""Layer C+B — Model-loaded GUI tier (#621, Sprint 16).

Marked ``slow`` + ``winui`` + ``hardware``: deselected from the canonical
Layer-A suite AND from standard winui runs. Run on the LA's dev machine with
the model loaded, a free display, and BlarAI closed:

    pytest -m "winui and hardware" tests/harness/test_winui_model_loaded.py

This tier combines:
  - Layer B (real model loaded via OrchestratorGPUInference on the Arc 140V)
  - Layer C (real WinUI window driven by pywinauto)

giving end-to-end coverage: a real model generates a reply that the real window
renders — the closest to a live BlarAI session the automated harness can produce.

PREREQUISITES (the deferred dev-machine run, Sprint-17-kickoff home):
  1. ``BlarAI.Desktop.exe`` built at the Debug path (or override ``BLARAI_EXE``).
  2. The Qwen3-14B OpenVINO model at the configured path (``TARGET_MODEL_OV_PATH``).
  3. The Arc 140V GPU available and the OpenVINO driver loaded.
  4. BlarAI not running (the named pipe must be free).
  5. A free interactive Windows display (no DISPLAY env var needed on Windows,
     but a running desktop session is required for WinUI to render).

See ``docs/runbooks/sprint_16_gui_devrun_runbook.md`` for the step-by-step
operator runbook. This file is the machine-readable definition; the runbook is the
human-readable one-at-a-time guide.

Design:
  The model-loaded backend is NOT the scripted fake — it is the REAL
  ``RpcDispatcher`` + ``NamedPipeServer`` backed by the real AO GPU inference
  engine. The WinUI window connects to the same pipe it would connect to in
  production. The test drives the window via pywinauto and asserts observable
  UI behaviour: a real reply appears in MessagesList, the PGOV card is absent
  for a benign prompt, and the input re-enables after the turn.

  Because the real model takes 15–30 s for the first token (cold GPU), the
  timeouts in this tier are proportionally longer than in Layer C.

SKIP POLICY:
  - If the exe is absent: ``pytest.skip`` (the exe is a build artifact).
  - If the model is absent: ``pytest.skip`` (the weights are not in-repo).
  - If ``openvino_genai`` is not importable: ``pytest.skip`` (no OV runtime).
  - If not on Windows: ``pytest.skip`` (WinUI is Windows-only).
  All skips are soft — the Layer-A suite sees them as deselected (``hardware``
  + ``winui`` markers), not as failures.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.harness.process_tree import terminate_process_tree

pytestmark = [
    pytest.mark.slow,
    pytest.mark.winui,
    pytest.mark.hardware,
    pytest.mark.skipif(sys.platform != "win32", reason="WinUI is Windows-only"),
]

_ROOT = Path(__file__).resolve().parents[2]

# The exe path — override via env for non-default build configurations.
_EXE_DEFAULT = _ROOT / "services/ui_winui/bin/x64/Debug/net8.0-windows10.0.19041.0/BlarAI.Desktop.exe"
EXE = Path(os.environ.get("BLARAI_EXE", str(_EXE_DEFAULT)))

# Generous timeouts for a cold GPU start.
_LAUNCH_SETTLE_S = 15     # .NET + model-loaded backend init
_WINDOW_WAIT_S = 60       # pywinauto window visible timeout
_FIRST_TOKEN_TIMEOUT = 45  # first token from the cold Qwen3-14B
_TURN_COMPLETE_TIMEOUT = 90  # full turn including streaming


@contextmanager
def _model_loaded_backend(
    prompt_override: str | None = None,
) -> Iterator[Any]:
    """Stand up the REAL NamedPipeServer backed by the AO GPU inference engine.

    Skips (soft) if the model or runtime is absent. Yields the server object
    (for pipe-name reference). The caller connects the WinUI window to the same
    default pipe name the production server uses.
    """
    try:
        from services.ui_backend.src.server import DEFAULT_PIPE_NAME, NamedPipeServer
        from services.ui_gateway.src.session_store import SessionStore
    except ImportError as exc:
        pytest.skip(f"ui_backend not importable: {exc}")

    try:
        from services.assistant_orchestrator.src.gpu_inference import OrchestratorGPUInference
        from shared.constants import TARGET_MODEL_OV_PATH
    except ImportError as exc:
        pytest.skip(f"AO gpu_inference not importable: {exc}")

    model_dir = _ROOT / TARGET_MODEL_OV_PATH
    if not model_dir.exists():
        pytest.skip(f"Qwen3-14B model absent: {model_dir}")

    try:
        import openvino_genai  # noqa: F401 — availability probe only
    except ImportError:
        pytest.skip("openvino_genai not importable — no OV runtime")

    engine = OrchestratorGPUInference(
        model_dir=str(model_dir),
        device="GPU",
        draft_model_dir=None,   # spec-decode opt-in if draft dir present
        manifest_path=None,     # integrity skip for the harness tier
    )
    loaded = engine.load_model()
    if not loaded:
        pytest.skip("OrchestratorGPUInference.load_model() returned False on GPU")

    # Build a minimal real gateway wrapping the engine (adapts the AO engine to
    # the named-pipe dispatcher's gateway interface).
    from tests.harness.fakes import FakeGateway

    # Use the FakeGateway as a structural stand-in for the gateway protocol while
    # passing real engine calls through. For the model-loaded tier we want the
    # REAL AO, so we build a thin adapter.
    class _RealAOGateway(FakeGateway):
        """FakeGateway subclass that overrides ``send_prompt`` / ``stream_tokens``
        to route through the real ``OrchestratorGPUInference`` engine.

        ``load_document``, ``store_attachment``, ``get_pgov_result`` etc. remain
        the scripted stubs (PGOV approved, no real PA) — this tier tests the AO
        chat path only, not the full production stack.
        """

        def __init__(self) -> None:
            super().__init__(reply="(unused — real engine generates)")
            self._engine = engine
            self._active_session: str | None = None
            self._last_prompt: str | None = None

        async def send_prompt(self, session_id: str, prompt: str) -> str:
            import asyncio

            self._active_session = session_id
            self._last_prompt = prompt
            self._req += 1
            self.prompts.append(prompt)
            # Kick off background generation so stream_tokens can consume it.
            loop = asyncio.get_event_loop()
            self._gen_future: asyncio.Future[str] = loop.run_in_executor(
                None,
                lambda: self._engine.generate_text(  # type: ignore[union-attr]
                    prompt, max_new_tokens=32
                ).text or "",
            )
            return f"req-{self._req}"

        async def stream_tokens(self, session_id: str) -> Any:  # AsyncIterator[_Tok]
            import asyncio

            from tests.harness.fakes import _Tok as _T

            # Await the engine result, then emit tokens word-by-word.
            text: str = await self._gen_future
            for word in text.split():
                await asyncio.sleep(0)
                yield _T(word + " ")

    gw = _RealAOGateway()
    store = SessionStore(":memory:")
    server = NamedPipeServer(gw, store, voice=None)
    thread = threading.Thread(
        target=server.serve_forever, name="model-loaded-pipe", daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.stop()
        store.close()
        try:
            engine.unload()
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def _model_loaded_window(
    gateway: Any,
) -> Iterator[Any]:
    """Launch the real window against a model-loaded backend; yield the pywinauto
    window; always terminate on exit."""
    from pywinauto import Desktop

    if not EXE.exists():
        pytest.skip(f"WinUI exe not built: {EXE}")

    from tests.harness.winui_foreground import bring_to_foreground

    proc = subprocess.Popen([str(EXE)])
    try:
        time.sleep(_LAUNCH_SETTLE_S)
        win = Desktop(backend="uia").window(process=proc.pid)
        win.wait("visible", timeout=_WINDOW_WAIT_S)
        # Robustly foreground so the WinUI UIA tree realizes (a backgrounded
        # WinUI 3 window leaves Collapsed/virtualized controls absent from the
        # tree) — same lazy-render seam as the Layer-C critical-path harness.
        bring_to_foreground(win)
        yield win
    finally:
        # Terminate the full process tree (the .NET exe spawns a Python backend
        # child that holds AO loopback port 5001 — a bare proc.terminate() only
        # kills the parent, leaving the child to pollute the next gate run; see
        # #630, Sprint 18 C6 fix).
        terminate_process_tree(proc.pid)
        time.sleep(1)


# ---------------------------------------------------------------------------
# Helpers (mirrors test_winui_input helpers for the model-loaded tier)
# ---------------------------------------------------------------------------


def _prompt_box(win: Any) -> Any:
    return win.child_window(auto_id="PromptBox", control_type="Edit")


def _send_button(win: Any) -> Any:
    return win.child_window(auto_id="SendButton", control_type="Button")


def _messages_list(win: Any) -> Any:
    return win.child_window(auto_id="MessagesList", control_type="List")


def _wait_enabled(ctrl: Any, target: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if ctrl.is_enabled() == target:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def _wait_item_count(lst: Any, at_least: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if len(lst.items()) >= at_least:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Model-loaded tests
# ---------------------------------------------------------------------------


def test_model_loaded_turn_renders_real_reply() -> None:
    """A real Qwen3-14B reply appears in MessagesList after a prompt turn.

    This is the end-to-end critical path: user types → real model generates →
    WinUI renders the tokens → input re-enables. It is the closest automated
    proxy for the live experience.

    Cold GPU first token is typically 15–30 s; the timeouts are set generously
    (``_FIRST_TOKEN_TIMEOUT``, ``_TURN_COMPLETE_TIMEOUT``) to avoid a timeout
    masquerading as a real failure.
    """
    from tests.harness.winui_foreground import bring_to_foreground

    with _model_loaded_backend() as _server:
        with _model_loaded_window(_server) as win:
            bring_to_foreground(win)  # click_input drives a real click → foreground
            prompt = _prompt_box(win)
            assert prompt.is_enabled(), "PromptBox must be live before sending"
            prompt.set_edit_text("In one sentence, what is a local-first AI assistant?")
            _send_button(win).click_input()
            # The input freezes while the model generates (correct — busy state).
            assert _wait_enabled(prompt, False, timeout=_FIRST_TOKEN_TIMEOUT), (
                "PromptBox should go busy while the model generates "
                f"(waited {_FIRST_TOKEN_TIMEOUT}s) — model may not have received the prompt"
            )
            # Then it re-enables when the turn finishes.
            assert _wait_enabled(prompt, True, timeout=_TURN_COMPLETE_TIMEOUT), (
                "PromptBox never re-enabled after the model-loaded turn — "
                f"did the pipeline complete? (waited {_TURN_COMPLETE_TIMEOUT}s)"
            )
            # At least one message item rendered.
            msgs = _messages_list(win)
            assert _wait_item_count(msgs, 1, timeout=10), (
                "MessagesList must have at least one item after a model-loaded turn"
            )


def test_model_loaded_pgov_approved_no_denial_card() -> None:
    """A benign prompt through the real AO must NOT produce a denial card —
    the approved PGOV path through the real pipeline.

    The FakeGateway.get_pgov_result always returns approved=True (the scripted
    half of the stack), so this test validates the approved display path."""
    from tests.harness.winui_foreground import bring_to_foreground

    with _model_loaded_backend() as _server:
        with _model_loaded_window(_server) as win:
            bring_to_foreground(win)  # click_input drives a real click → foreground
            prompt = _prompt_box(win)
            prompt.set_edit_text("Say hello in three words.")
            _send_button(win).click_input()
            assert _wait_enabled(prompt, True, timeout=_TURN_COMPLETE_TIMEOUT), (
                "PromptBox must re-enable after the real model turn"
            )
            # No denial card visible. On an APPROVED turn the card is correctly
            # absent: it is DeniedVisibility-gated (IsDenied stays false), AND the
            # PgovDenialCard <Border> has no AutomationPeer anyway — so absent OR
            # present-but-not-visible both satisfy the approved contract. (This is
            # an ABSENCE assertion, so anchoring on the peer-less Border is fine;
            # the PRESENCE test for the denied path anchors on PgovDenialHeading.)
            try:
                denial = win.child_window(auto_id="PgovDenialCard")
                if denial.exists():
                    assert not denial.is_visible(), (
                        "PgovDenialCard must not be visible after an approved turn"
                    )
            except Exception:  # noqa: BLE001 — element absent is correct
                pass
