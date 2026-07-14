"""
BlarAI TUI Shell — Main Application (P1.12, ADR-009)
=====================================================

DEPRECATED (2026-06-02): The Textual TUI is no longer the primary interaction
surface. The native WinUI 3 app (ADR-014) supersedes it for daily use and has
reached and exceeded feature parity (chat, markdown streaming, multimodal
attachments, persistent semantic memory, theming, and voice). Per the
User-Operator's explicit call, the TUI is **retained in-tree, dormant — not
deleted**: it still runs as a fallback surface and stays under test coverage.
New capabilities are wired in the UI backend (ADR-014) and surfaced by WinUI;
do not extend the TUI. See ADR-009 (status: Superseded by ADR-014 for the
primary surface; retained as fallback) and ADR-014.

Textual App subclass providing the three-region layout:

  ┌──────────┬───────────────────────────────┐
  │ Sessions │  Response / Streaming Area    │
  │  Panel   │                               │
  │          ├───────────────────────────────│
  │          │  Prompt Input                 │
  └──────────┴───────────────────────────────┘

Boot-Phase-3 gating: the prompt input is DISABLED until the
Transport Gateway reaches OPERATIONAL state. While HANDSHAKING
or INITIALIZING, a spinner + status label is displayed instead.

Keyboard shortcuts:
  Enter     — submit prompt
  Ctrl+R    — retry last failed prompt
  Ctrl+N    — new session
  Ctrl+D    — delete current session
  Ctrl+Q    — quit
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListView, Static

from services.ui_gateway.src.constants import (
    PA_HANDSHAKE_MAX_RETRIES,
    pa_handshake_backoff_schedule,
)

from .constants import (
    BOOT_BANNER_TEXT,
    BOOT_FAILED_TEXT,
    BOOT_STATUS_POLL_INTERVAL_S,
    KEY_DELETE_SESSION,
    KEY_NEW_SESSION,
    KEY_PASTE,
    KEY_QUIT,
    KEY_RETRY,
    KEY_SUBMIT,
    PROMPT_MAX_CHARS,
    SESSION_PANEL_WIDTH_PCT,
)
from services.ui_gateway.src.document_loader import DocumentLoadError
from .pgov_display import PGOVPanel
from .session_panel import SessionListItem, SessionPanel
from .streaming import StreamingDisplay

if TYPE_CHECKING:
    from services.ui_gateway.src.session_store import SessionStore
    from services.ui_gateway.src.transport import StartupState, TransportGateway

logger = logging.getLogger(__name__)


class _ISO8601Formatter(logging.Formatter):
    """Formatter that emits UTC ISO-8601 timestamps."""

    def formatTime(
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        return datetime.fromtimestamp(
            record.created, timezone.utc
        ).isoformat(timespec="seconds")


def _configure_boot_logger() -> logging.Logger:
    """Configure a dedicated boot logger writing to %LOCALAPPDATA%\\BlarAI\\boot.log."""
    boot_logger = logging.getLogger("blarai.boot")
    boot_logger.setLevel(logging.INFO)
    boot_logger.propagate = False

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return boot_logger

    boot_dir = os.path.join(local_appdata, "BlarAI")
    os.makedirs(boot_dir, exist_ok=True)
    boot_log_path = os.path.join(boot_dir, "boot.log")

    for handler in boot_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            if handler.baseFilename == boot_log_path:
                return boot_logger

    file_handler = logging.FileHandler(boot_log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(_ISO8601Formatter("%(asctime)s %(message)s"))
    boot_logger.addHandler(file_handler)
    return boot_logger


class BootBanner(Static):
    """Displayed while the system is starting up."""

    DEFAULT_CSS = """
    BootBanner {
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-style: bold;
    }
    """


class BlarAIApp(App[None]):
    """Primary TUI application for BlarAI (ADR-009).

    Parameters
    ----------
    gateway : TransportGateway | None
        Pre-constructed gateway instance (injected at startup).
    session_store : SessionStore | None
        SQLite session persistence (injected at startup).
    """

    TITLE = "BlarAI Assistant"
    CSS_PATH = None  # inline CSS only for now

    BINDINGS = [
        Binding(KEY_SUBMIT, "submit_prompt", "Submit", show=False),
        Binding(KEY_RETRY, "retry_boot", "Retry"),
        Binding(KEY_NEW_SESSION, "new_session", "New Session"),
        Binding(KEY_DELETE_SESSION, "delete_session", "Delete Session"),
        Binding(KEY_PASTE, "paste_clipboard", "Paste", show=False, priority=True),
        Binding(KEY_QUIT, "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    #session-panel {
        width: 25%;
        dock: left;
    }
    #main-area {
        width: 75%;
    }
    #response-area {
        height: 1fr;
    }
    #prompt-input {
        dock: bottom;
        height: 3;
    }
    #pgov-panel {
        dock: bottom;
        height: auto;
        max-height: 30%;
        display: none;
    }
    """

    def __init__(
        self,
        gateway: TransportGateway | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        super().__init__()
        self._gateway = gateway
        self._session_store = session_store
        self._operational: bool = False
        self._last_prompt: str = ""
        self._boot_task: asyncio.Task[None] | None = None
        self._boot_logger: logging.Logger = _configure_boot_logger()
        self._last_boot_state: StartupState | None = None

    def _log_boot_state(self, state: str, detail: str = "") -> None:
        """Log startup state transition to the dedicated boot logger."""
        if detail:
            self._boot_logger.info("%s | %s", state, detail)
            return
        self._boot_logger.info(state)

    def _write_boot_banner(self, text: str) -> None:
        """Append a startup status line to the response area."""
        banner = self.query_one("#response-area", StreamingDisplay)
        banner.write_line(text)

    # ── Compose ───────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield SessionPanel(store=self._session_store, id="session-panel")
            with Vertical(id="main-area"):
                yield StreamingDisplay(id="response-area")
                yield PGOVPanel(id="pgov-panel")
                yield Input(
                    placeholder="Type your message…",
                    id="prompt-input",
                    max_length=PROMPT_MAX_CHARS,
                    disabled=True,
                )
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────

    async def on_mount(self) -> None:
        """Start boot-phase-3 polling."""
        self._boot_logger = _configure_boot_logger()
        self._boot_task = asyncio.create_task(self._poll_boot_status())

    async def _poll_boot_status(self) -> None:
        """Poll gateway status until OPERATIONAL or FAILED.

        ``check_pa_status()`` returns ``bool``: True on successful PA
        handshake, False after max retries exhausted. The gateway's
        internal ``state`` property transitions to ``OPERATIONAL`` or
        ``FAILED`` accordingly.

        Fail-Closed: if no gateway is injected, the app stays disabled.
        """
        if self._gateway is None:
            self._log_boot_state("FAILED", "gateway missing")
            self._write_boot_banner(BOOT_FAILED_TEXT)
            return

        self._operational = False
        self._last_boot_state = None
        self._write_boot_banner(BOOT_BANNER_TEXT)
        self._log_boot_state("INITIALIZING", "boot polling started")

        check_task: asyncio.Task[bool] = asyncio.create_task(
            self._gateway.check_pa_status()
        )
        start_time = asyncio.get_running_loop().time()
        # #808: the banner's attempt markers derive from the SAME backoff
        # schedule the gateway's retry loop executes (capped exponential,
        # aggregate 180 s) — a single source of truth so the display can
        # never disagree with the budget (lesson 221).
        backoff_schedule: tuple[float, ...] = pa_handshake_backoff_schedule()
        attempt_markers: list[float] = [0.0]
        elapsed = 0.0
        for delay in backoff_schedule:
            elapsed += delay
            attempt_markers.append(elapsed)

        initial_detail = (
            f"attempt 1/{PA_HANDSHAKE_MAX_RETRIES} "
            f"(next backoff: {backoff_schedule[0]:.1f}s)"
        )
        self._write_boot_banner(
            f"[yellow]Connecting to Policy Agent…[/yellow] {initial_detail}"
        )
        self._log_boot_state("HANDSHAKING", initial_detail)

        attempt_displayed = 1
        while not check_task.done():
            current_state = self._gateway.state
            if current_state != self._last_boot_state:
                self._log_boot_state(current_state.value)
                self._last_boot_state = current_state

            if current_state.value == "HANDSHAKING":
                elapsed_s = asyncio.get_running_loop().time() - start_time
                while (
                    attempt_displayed < PA_HANDSHAKE_MAX_RETRIES
                    and elapsed_s >= attempt_markers[attempt_displayed]
                ):
                    attempt_num = attempt_displayed + 1
                    next_backoff = (
                        backoff_schedule[attempt_displayed]
                        if attempt_displayed < len(backoff_schedule)
                        else 0.0
                    )
                    if attempt_num < PA_HANDSHAKE_MAX_RETRIES:
                        detail = (
                            f"attempt {attempt_num}/{PA_HANDSHAKE_MAX_RETRIES} "
                            f"(next backoff: {next_backoff:.1f}s)"
                        )
                    else:
                        detail = f"attempt {attempt_num}/{PA_HANDSHAKE_MAX_RETRIES}"

                    self._write_boot_banner(
                        f"[yellow]Connecting to Policy Agent…[/yellow] {detail}"
                    )
                    self._log_boot_state("HANDSHAKING", detail)
                    attempt_displayed += 1

            await asyncio.sleep(BOOT_STATUS_POLL_INTERVAL_S)

        ok = await check_task
        if ok:
            self._operational = True
            prompt = self.query_one("#prompt-input", Input)
            prompt.disabled = False
            prompt.focus()
            self._write_boot_banner("[green]System ready.[/green]")
            self._log_boot_state("OPERATIONAL", "input enabled")
            logger.info("Boot-Phase-3: OPERATIONAL — input enabled")
        else:
            self._write_boot_banner(BOOT_FAILED_TEXT)
            self._log_boot_state("FAILED", "fail-closed after handshake retries")
            logger.error("Boot-Phase-3: FAILED — Fail-Closed, input disabled")

    # ── Event Handlers ────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the prompt Input widget."""
        if event.input.id == "prompt-input":
            await self.action_submit_prompt()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle click / Enter on a session in the sidebar ListView."""
        item = event.item
        if not isinstance(item, SessionListItem):
            return
        panel = self.query_one("#session-panel", SessionPanel)
        await panel.select_session(item.session_id)
        # Reload conversation display for the selected session
        display = self.query_one("#response-area", StreamingDisplay)
        display.clear_display()
        pgov_panel = self.query_one("#pgov-panel", PGOVPanel)
        pgov_panel.hide()

        # Load persisted turns and render into the display
        if self._session_store is not None:
            turns = await asyncio.to_thread(
                self._session_store.get_turns, item.session_id
            )
            for turn in turns:
                if turn.role == "user":
                    display.write_line(f"[bold cyan]You:[/bold cyan] {turn.content}")
                else:
                    display.write_line(f"{turn.content}")
                    if turn.pgov_status == "denied" and turn.pgov_reasons:
                        display.write_line(
                            f"[dim red]PGov denied: {', '.join(turn.pgov_reasons)}[/dim red]"
                        )
                display.write_line("─" * 40)

    # ── Helpers ───────────────────────────────────────────────────

    async def _ensure_session(self) -> str | None:
        """Return active session ID, creating one if needed.

        Returns None (Fail-Closed) if no SessionStore is available.
        """
        panel = self.query_one("#session-panel", SessionPanel)

        if panel.active_session_id is not None:
            return panel.active_session_id

        # No active session — create one
        if self._session_store is None:
            return None

        session_id = await asyncio.to_thread(self._session_store.create_session)
        await asyncio.to_thread(
            self._session_store.set_active_session, session_id
        )
        await panel.refresh_list()
        return panel.active_session_id

    # ── Actions ───────────────────────────────────────────────────

    async def action_submit_prompt(self) -> None:
        """Send the current prompt to the orchestrator via gateway."""
        if not self._operational or self._gateway is None:
            return

        prompt_input = self.query_one("#prompt-input", Input)
        text = prompt_input.value.strip()
        if not text:
            return

        self._last_prompt = text
        prompt_input.value = ""
        prompt_input.disabled = True

        display = self.query_one("#response-area", StreamingDisplay)
        pgov_panel = self.query_one("#pgov-panel", PGOVPanel)
        pgov_panel.hide()

        # ── /load command handling ─────────────────────────────────────
        # Intercept before any prompt dispatch. The command is handled
        # locally (no prompt sent to the Orchestrator).
        _LOAD_PREFIX = "/load "
        if text.startswith(_LOAD_PREFIX):
            filename = text[len(_LOAD_PREFIX):].strip()
            session_id = await self._ensure_session()
            if session_id is None:
                display.write_line("[red]No session available (Fail-Closed).[/red]")
                prompt_input.disabled = False
                prompt_input.focus()
                return
            display.start_new_response()
            try:
                result = await asyncio.to_thread(
                    self._gateway.load_document, session_id, filename
                )
                size_kb = result["size_bytes"] / 1024
                display.write_line(
                    f"[green]Loaded {result['filename']} ({size_kb:.1f} KB)"
                    " — ask me about it.[/green]"
                )
                injection_warnings = result.get("injection_warnings") or []
                if injection_warnings:
                    display.write_line(
                        "[yellow]⚠ This document contains text that looks like "
                        "instructions to the assistant (possible prompt "
                        "injection). BlarAI treats document content as data, "
                        "but read its answers about this file with extra "
                        "care.[/yellow]"
                    )
            except DocumentLoadError as exc:
                display.write_line(f"[red]Load failed: {exc}[/red]")
            except Exception as exc:
                display.write_line(
                    f"[red]Unexpected error loading document — Fail-Closed: {exc}[/red]"
                )
                logger.error("action_submit_prompt /load unexpected: %s", exc, exc_info=True)
            prompt_input.disabled = False
            prompt_input.focus()
            return
        # ── end /load ──────────────────────────────────────────────────

        # ── /ls command handling ────────────────────────────────────────
        # Lists files in userdata/ that /load accepts. Pure host-side
        # operation; never sent to the model. Helpful so the user does
        # not have to switch to a file manager to recall a filename.
        if text == "/ls":
            display.start_new_response()
            try:
                files = self._gateway.list_userdata_files()
                if not files:
                    display.write_line(
                        "[yellow]No loadable files in userdata/. "
                        "Drop a .txt, .md, or .pdf in "
                        "C:\\Users\\mrbla\\BlarAI\\userdata\\ and "
                        "try again.[/yellow]"
                    )
                else:
                    display.write_line(
                        "[green]Files in userdata/ — use /load <name> to load one:[/green]"
                    )
                    # Compute the right-pad width so the size column aligns.
                    name_width = max(len(str(f["filename"])) for f in files)
                    for f in files:
                        size_kb = f["size_kb"]
                        display.write_line(
                            f"  {str(f['filename']).ljust(name_width)}  ({size_kb} KB)"
                        )
            except Exception as exc:
                display.write_line(
                    f"[red]Unexpected error listing userdata/ — Fail-Closed: {exc}[/red]"
                )
                logger.error(
                    "action_submit_prompt /ls unexpected: %s", exc, exc_info=True
                )
            prompt_input.disabled = False
            prompt_input.focus()
            return
        # ── end /ls ────────────────────────────────────────────────────

        # ── /trust command handling ─────────────────────────────────────
        # Intercept like /load and /unload. Layer 3 (ADR-013) per-session
        # override: lets the user explicitly opt in to allowing tool calls
        # while a document is loaded, accepting the residual risk that the
        # document could influence tool use. Cleared by /unload or a new
        # session — never persists past the document.
        if text == "/trust":
            session_id = await self._ensure_session()
            if session_id is None:
                display.write_line("[red]No session available (Fail-Closed).[/red]")
                prompt_input.disabled = False
                prompt_input.focus()
                return
            display.start_new_response()
            try:
                self._gateway.trust_documents_for_tools(session_id)
                display.write_line(
                    "[yellow]Tools enabled for this session despite loaded "
                    "documents. You accept that documents in context could "
                    "influence tool calls. Use /unload or start a new "
                    "session to revoke.[/yellow]"
                )
            except Exception as exc:
                display.write_line(
                    f"[red]Unexpected error setting trust — Fail-Closed: {exc}[/red]"
                )
                logger.error(
                    "action_submit_prompt /trust unexpected: %s", exc, exc_info=True
                )
            prompt_input.disabled = False
            prompt_input.focus()
            return
        # ── end /trust ──────────────────────────────────────────────────

        # ── /unload command handling ────────────────────────────────────
        # Intercept like /load — clears loaded documents and is never sent
        # to the model, so the model cannot hallucinate a fake "unloaded"
        # reply that would poison the rest of the session.
        if text == "/unload":
            session_id = await self._ensure_session()
            if session_id is None:
                display.write_line("[red]No session available (Fail-Closed).[/red]")
                prompt_input.disabled = False
                prompt_input.focus()
                return
            display.start_new_response()
            try:
                self._gateway.unload_documents(session_id)
                display.write_line(
                    "[green]Loaded documents cleared — context reset.[/green]"
                )
            except Exception as exc:
                display.write_line(
                    f"[red]Unexpected error unloading documents — Fail-Closed: {exc}[/red]"
                )
                logger.error(
                    "action_submit_prompt /unload unexpected: %s", exc, exc_info=True
                )
            prompt_input.disabled = False
            prompt_input.focus()
            return
        # ── end /unload ─────────────────────────────────────────────────

        # ── /rename command handling ────────────────────────────────────
        # Intercept like /load — sets a custom, persisted title on the
        # active session. Never sent to the model. Unlike the auto-title,
        # /rename overwrites whatever title the session currently has.
        _RENAME_PREFIX = "/rename"
        if text == _RENAME_PREFIX or text.startswith(_RENAME_PREFIX + " "):
            new_title = text[len(_RENAME_PREFIX):].strip()
            panel = self.query_one("#session-panel", SessionPanel)
            session_id = panel.active_session_id
            display.start_new_response()
            if session_id is None:
                display.write_line(
                    "[yellow]No active session to rename — "
                    "start a session first.[/yellow]"
                )
            elif not new_title:
                display.write_line("[yellow]Usage: /rename <new title>[/yellow]")
            elif self._session_store is None:
                display.write_line(
                    "[red]No session store available (Fail-Closed).[/red]"
                )
            else:
                try:
                    await asyncio.to_thread(
                        self._session_store.update_session_title,
                        session_id,
                        new_title,
                    )
                    await panel.refresh_list()
                    display.write_line(
                        f"[green]Session renamed to: {escape(new_title)}[/green]"
                    )
                except Exception as exc:
                    display.write_line(
                        "[red]Unexpected error renaming session — "
                        f"Fail-Closed: {exc}[/red]"
                    )
                    logger.error(
                        "action_submit_prompt /rename unexpected: %s",
                        exc,
                        exc_info=True,
                    )
            prompt_input.disabled = False
            prompt_input.focus()
            return
        # ── end /rename ─────────────────────────────────────────────────

        # Ensure an active session exists
        session_id = await self._ensure_session()
        if session_id is None:
            display.write_line("[red]No session available (Fail-Closed).[/red]")
            prompt_input.disabled = False
            prompt_input.focus()
            return

        # ── /ingest, /approve, /reject + bare-URL interception (#655) ───
        # Mirrors the backend dispatcher's prompt arc (dispatcher._m_prompt):
        # the GATEWAY owns the interception and the informational-turn
        # persistence; this surface only renders the reply as ONE message —
        # no token streaming, no PGOV panel (the text is deterministic tool
        # output, never model output, never PGOV-validated).  getattr-guarded
        # like the dispatcher so stub/fake gateways without the ingest
        # surface keep the unchanged prompt arc; the iscoroutinefunction
        # check additionally keeps MagicMock-style test gateways — whose
        # auto-created attribute is not awaitable — on the old arc.
        ingest_handler = getattr(self._gateway, "handle_ingest_command", None)
        if ingest_handler is not None and inspect.iscoroutinefunction(ingest_handler):
            try:
                info_text = await ingest_handler(session_id, text)
            except Exception as exc:
                display.start_new_response()
                display.write_line(
                    f"[red]Ingest command failed — Fail-Closed: {exc}[/red]"
                )
                logger.error(
                    "action_submit_prompt ingest unexpected: %s", exc, exc_info=True
                )
                prompt_input.disabled = False
                prompt_input.focus()
                return
            if info_text is not None:
                display.start_new_response()
                display.write_line(f"[bold]You:[/bold] {text}")
                display.write_line(escape(info_text))
                # The gateway persisted both turns (user + informational
                # reply) — refresh the panel so the turn count and the
                # first-prompt auto-title update. Best-effort, like the
                # normal arc's epilogue refresh.
                if self._session_store is not None:
                    try:
                        panel = self.query_one("#session-panel", SessionPanel)
                        await panel.refresh_list()
                    except Exception as exc:
                        logger.error("session panel refresh failed: %s", exc)
                prompt_input.disabled = False
                prompt_input.focus()
                return
        # ── end ingest interception ──────────────────────────────────────

        display.start_new_response()
        display.write_line(f"[bold]You:[/bold] {text}")

        try:
            # Dispatch prompt — returns request_id for correlation
            request_id = await self._gateway.send_prompt(session_id, text)

            # Stream tokens from Orchestrator via IPC
            async for token in self._gateway.stream_tokens(session_id):
                display.append_token(token)

            # Retrieve PGOV result (sync method, run in thread)
            result = await asyncio.to_thread(
                self._gateway.get_pgov_result, request_id
            )

            if not result.approved:
                pgov_panel.display_denial(result)
                # Discard buffered tool-call tokens
                self._gateway.flush_tool_call_buffer(pgov_approved=False)
                # Persist denied assistant turn
                if self._session_store is not None:
                    await asyncio.to_thread(
                        self._session_store.add_turn,
                        session_id,
                        "assistant",
                        result.sanitized_text,
                        "denied",
                        result.reason_codes,
                    )
            else:
                # Flush approved tool-call tokens
                approved_tokens = self._gateway.flush_tool_call_buffer(
                    pgov_approved=True
                )
                for tc_token in approved_tokens:
                    display.append_token(tc_token)

                # Persist approved assistant turn (collect displayed text)
                if self._session_store is not None:
                    await asyncio.to_thread(
                        self._session_store.add_turn,
                        session_id,
                        "assistant",
                        result.sanitized_text or "(approved response)",
                        "approved",
                        [],
                    )

        except RuntimeError as exc:
            display.write_line(f"[red]Error: {exc}[/red]")
            logger.error("action_submit_prompt failed: %s", exc)
        except Exception as exc:
            display.write_line(
                "[red]Unexpected error — Fail-Closed.[/red]"
            )
            logger.error("action_submit_prompt unexpected: %s", exc, exc_info=True)

        # Refresh the session panel so the updated turn count — and the
        # auto-title applied on the session's first prompt — appear
        # immediately. Best-effort: a refresh failure must not break the
        # prompt flow.
        if self._session_store is not None:
            try:
                panel = self.query_one("#session-panel", SessionPanel)
                await panel.refresh_list()
            except Exception as exc:
                logger.error("session panel refresh failed: %s", exc)

        prompt_input.disabled = False
        prompt_input.focus()

    async def action_retry_boot(self) -> None:
        """Retry startup handshake, or re-submit the last prompt if operational."""
        if self._operational:
            if self._last_prompt:
                prompt_input = self.query_one("#prompt-input", Input)
                prompt_input.value = self._last_prompt
                await self.action_submit_prompt()
            return

        if self._gateway is None:
            return

        if self._boot_task is not None and not self._boot_task.done():
            self._boot_task.cancel()

        await asyncio.to_thread(self._gateway.reset)
        self._write_boot_banner("[yellow]Retrying boot…[/yellow]")
        self._log_boot_state("INITIALIZING", "manual retry requested")
        self._boot_task = asyncio.create_task(self._poll_boot_status())

    async def action_new_session(self) -> None:
        """Create a new conversation session."""
        panel = self.query_one("#session-panel", SessionPanel)
        await panel.create_new_session()
        # Clear display for new session context
        display = self.query_one("#response-area", StreamingDisplay)
        display.clear_display()
        pgov_panel = self.query_one("#pgov-panel", PGOVPanel)
        pgov_panel.hide()

    async def action_delete_session(self) -> None:
        """Delete the current conversation session."""
        panel = self.query_one("#session-panel", SessionPanel)
        await panel.delete_current_session()
        # Clear display after deletion
        display = self.query_one("#response-area", StreamingDisplay)
        display.clear_display()
        pgov_panel = self.query_one("#pgov-panel", PGOVPanel)
        pgov_panel.hide()

    async def action_paste_clipboard(self) -> None:
        """Paste system clipboard contents into the prompt input.

        Adds an explicit Ctrl+V handler at the app level so paste works
        in terminals that intercept the keystroke and prevent Textual's
        built-in Input.action_paste from firing. Reads via pyperclip
        (pure Python, OS clipboard utilities). Failures are surfaced to
        the response area rather than crashing the TUI.
        """
        try:
            import pyperclip  # local import — only paste needs it
        except ImportError:
            display = self.query_one("#response-area", StreamingDisplay)
            display.write_line(
                "[red]Paste failed: pyperclip is not installed. "
                "Run `pip install pyperclip` in the BlarAI venv.[/red]"
            )
            return
        try:
            clipboard_text = pyperclip.paste()
        except Exception as exc:  # noqa: BLE001 — surface any clipboard error
            display = self.query_one("#response-area", StreamingDisplay)
            display.write_line(
                f"[red]Paste failed: could not read clipboard ({exc}).[/red]"
            )
            return
        if not clipboard_text:
            return  # nothing to paste — silent no-op
        # Cap to the prompt-max so we never paste more than the input box
        # is willing to accept, and so a huge paste cannot lock the UI.
        if len(clipboard_text) > PROMPT_MAX_CHARS:
            clipboard_text = clipboard_text[:PROMPT_MAX_CHARS]
        prompt_input = self.query_one("#prompt-input", Input)
        # Insert at the current cursor position. Input.insert_text_at_cursor
        # is the supported public method; it handles cursor advancement.
        prompt_input.insert_text_at_cursor(clipboard_text)
        prompt_input.focus()
