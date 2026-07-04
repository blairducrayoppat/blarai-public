"""
UI Backend RPC Dispatcher (ADR-014)
====================================
Transport-agnostic core: maps a decoded request dict to the right
:class:`TransportGateway` / :class:`SessionStore` call and emits one or more
response frames through an injected async ``send`` callback. Keeping the
dispatch logic here — with no pipe, socket, or pywin32 dependency — means it is
fully unit-testable against fakes, and the named-pipe server is a thin shell
over it.

This is also the single source of truth for the chat orchestration the TUI
currently performs inline in ``app.action_submit_prompt`` (send prompt -> stream
tokens -> resolve PGOV -> persist the assistant turn). The WinUI front end stays
a thin view by calling the ``prompt`` method and rendering the frames it emits.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from services.ui_backend.src.protocol import (
    error_response,
    ok_response,
    stream_frame,
)

logger = logging.getLogger(__name__)

# Async sink the server injects: receives one fully-formed response frame.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]

_SENTINEL = object()

# Fail-safe deadline for the entire _m_prompt streaming + PGOV + store arc.
# If the gateway stalls (GENERATION_COMPLETE never arrives, IPC hangs, or any
# other unresolved await), _m_prompt cancels the arc and emits a terminal
# ``end`` frame so the WinUI front end's input is never frozen longer than
# this bound.  Chosen well under the 180 s per-socket receive timeout
# (PROMPT_RESPONSE_TIMEOUT_S) so a missing GENERATION_COMPLETE surfaces as a
# bounded, user-visible stall rather than a multi-minute freeze (Vikunja #565
# tracks the memory root cause; this constant guards the symptom regardless of
# root cause). Intentionally generous: fast answers complete in seconds; the
# bound just prevents the worst-case open-ended hang.
#
# Tests that need a tighter bound should construct RpcDispatcher with
# prompt_stream_failsafe_s= keyword argument rather than patching this module
# constant.
_PROMPT_STREAM_FAILSAFE_S: float = 90.0

# Image generation (/imagine, /edit) is a heavyweight, multi-pass operation when
# hires-fix is on (base 1024² + a 1536² refine + a diffusion-pipeline swap), and
# it evicts the 14B for the duration (UC-010 #666). That runs far longer than a
# chat turn (~100 s), so the imagine interception gets its OWN, longer fail-safe —
# kept just under the 180 s per-socket receive cap (PROMPT_RESPONSE_TIMEOUT_S) so
# the result still arrives before the socket closes.
_IMAGINE_STREAM_FAILSAFE_S: float = 175.0

# Best-effort voice diagnostics log (ADR-017 bring-up). Appended to so a failed
# transcribe/synthesize leaves a trace even when stderr is not visible.
_VOICE_LOG = Path(r"C:\Users\mrbla\BlarAI\userdata\_voice_backend.log")


def _voice_log(msg: str) -> None:
    try:
        with _VOICE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:  # noqa: BLE001 — diagnostics must never break a request
        pass


def _next_or_none(iterator: Any) -> Any | None:
    """Pull the next item from *iterator*, or ``None`` when exhausted.

    Used to step a synchronous generator from a worker thread without letting
    ``StopIteration`` cross the ``asyncio.to_thread`` boundary.
    """
    value = next(iterator, _SENTINEL)
    return None if value is _SENTINEL else value


class RpcDispatcher:
    """Dispatch decoded RPC requests to the gateway / session store.

    Args:
        gateway: A :class:`TransportGateway` (or compatible) instance.
        session_store: A :class:`SessionStore` (or compatible) instance, or
            ``None`` for an ephemeral (no-persistence) backend.
    """

    def __init__(
        self,
        gateway: Any,
        session_store: Any | None = None,
        voice: Any | None = None,
        prompt_stream_failsafe_s: float | None = None,
        imagine_failsafe_s: float | None = None,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            gateway: A TransportGateway (or compatible) instance.
            session_store: A SessionStore (or compatible) instance, or None for
                ephemeral (no-persistence) operation.
            voice: A VoiceEngine (or compatible) instance, or None to disable
                voice features.
            prompt_stream_failsafe_s: Override the ``_PROMPT_STREAM_FAILSAFE_S``
                deadline for the streaming arc.  ``None`` (default) uses the
                module constant. Provide a shorter value in tests that need the
                fail-safe to fire quickly without waiting 90 s.
            imagine_failsafe_s: Override the ``_IMAGINE_STREAM_FAILSAFE_S``
                deadline for the /imagine interception (heavier than a chat turn —
                hires + 14B eviction). ``None`` uses the module constant.
        """
        self._gateway = gateway
        self._store = session_store
        self._voice = voice
        self._prompt_stream_failsafe_s: float = (
            prompt_stream_failsafe_s
            if prompt_stream_failsafe_s is not None
            else _PROMPT_STREAM_FAILSAFE_S
        )
        self._imagine_failsafe_s: float = (
            imagine_failsafe_s
            if imagine_failsafe_s is not None
            else _IMAGINE_STREAM_FAILSAFE_S
        )

    async def handle(self, request: dict[str, Any], send: SendFn) -> None:
        """Route one request to its handler and emit the response frame(s)."""
        rid = request.get("id")
        method = request.get("method")
        raw_params = request.get("params")
        if raw_params is None:
            params: dict[str, Any] = {}
        elif isinstance(raw_params, dict):
            params = raw_params
        else:
            await send(error_response(rid, "bad_params", "params must be an object"))
            return

        handler = getattr(self, f"_m_{method}", None)
        if handler is None:
            await send(error_response(rid, "unknown_method", f"Unknown method: {method!r}"))
            return

        try:
            await handler(rid, params, send)
        except KeyError as exc:
            await send(error_response(rid, "missing_param", f"Missing parameter: {exc}"))
        except Exception as exc:  # noqa: BLE001 — Fail-Closed: every failure -> error frame
            cid = secrets.token_hex(4)
            logger.error(
                "dispatch %r failed [cid=%s]: %s", method, cid, exc, exc_info=True
            )
            await send(
                error_response(rid, "internal_error", f"internal error [{cid}]")
            )

    # ── Session methods ───────────────────────────────────────────────

    async def _m_list_sessions(self, rid: Any, params: dict, send: SendFn) -> None:
        if self._store is None:
            await send(ok_response(rid, []))
            return
        sessions = [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "is_active": s.is_active,
                "turn_count": s.turn_count,
            }
            for s in self._store.list_sessions()
        ]
        await send(ok_response(rid, sessions))

    async def _m_get_turns(self, rid: Any, params: dict, send: SendFn) -> None:
        if self._store is None:
            await send(ok_response(rid, []))
            return
        turns = [
            {
                "id": t.id,
                "session_id": t.session_id,
                "role": t.role,
                "content": t.content,
                "pgov_status": t.pgov_status,
                "pgov_reasons": t.pgov_reasons,
                "timestamp": t.timestamp,
            }
            for t in self._store.get_session_turns(params["session_id"])
        ]
        await send(ok_response(rid, turns))

    async def _m_create_session(self, rid: Any, params: dict, send: SendFn) -> None:
        if self._store is None:
            await send(error_response(rid, "no_store", "Session store unavailable"))
            return
        session_id = self._store.create_session(title=params.get("title", ""))
        self._store.set_active_session(session_id)
        await send(ok_response(rid, {"session_id": session_id}))

    async def _m_set_active_session(self, rid: Any, params: dict, send: SendFn) -> None:
        if self._store is None:
            await send(error_response(rid, "no_store", "Session store unavailable"))
            return
        self._store.set_active_session(params["session_id"])
        await send(ok_response(rid, {"session_id": params["session_id"]}))

    async def _m_delete_session(self, rid: Any, params: dict, send: SendFn) -> None:
        if self._store is None:
            await send(error_response(rid, "no_store", "Session store unavailable"))
            return
        deleted = self._store.delete_session(params["session_id"])
        await send(ok_response(rid, {"deleted": deleted}))

    async def _m_rename_session(self, rid: Any, params: dict, send: SendFn) -> None:
        if self._store is None:
            await send(error_response(rid, "no_store", "Session store unavailable"))
            return
        updated = self._store.update_session_title(params["session_id"], params["title"])
        await send(ok_response(rid, {"updated": updated}))

    # ── Document / attachment methods ─────────────────────────────────

    async def _m_load_document(self, rid: Any, params: dict, send: SendFn) -> None:
        # Run the (blocking) disk read off the event loop. server.py drives one
        # run_until_complete loop per connection, so a synchronous load here
        # would freeze every other method sharing it — voice capture/transcribe,
        # chat streaming — until it returned. asyncio.to_thread keeps the loop
        # free; any DocumentLoadError still propagates to handle()'s error frame.
        result = await asyncio.to_thread(
            self._gateway.load_document, params["session_id"], params["filename"]
        )
        await send(ok_response(rid, result))

    async def _m_store_attachment(self, rid: Any, params: dict, send: SendFn) -> None:
        # The picker / drag-drop path: copy a file from anywhere on disk into
        # userdata/ and stage it for the session, identical to a typed /load.
        # The copy (up to 64 MB for an image) and the staged re-load are both
        # blocking I/O, so both run off the event loop (see _m_load_document).
        from services.ui_gateway.src.document_loader import store_attachment

        doc = await asyncio.to_thread(store_attachment, params["src_path"])
        session_id = params.get("session_id")
        if session_id:
            # Re-load through the gateway so it is staged for the next prompt
            # (and scanned for injection), mirroring the /load path exactly.
            result = await asyncio.to_thread(
                self._gateway.load_document, session_id, doc["filename"]
            )
        else:
            result = doc
        await send(ok_response(rid, result))

    async def _m_unload_documents(self, rid: Any, params: dict, send: SendFn) -> None:
        self._gateway.unload_documents(params["session_id"])
        await send(ok_response(rid, {"unloaded": True}))

    async def _m_list_userdata_files(self, rid: Any, params: dict, send: SendFn) -> None:
        await send(ok_response(rid, self._gateway.list_userdata_files()))

    async def _m_trust_documents_for_tools(self, rid: Any, params: dict, send: SendFn) -> None:
        self._gateway.trust_documents_for_tools(params["session_id"])
        await send(ok_response(rid, {"trusted": True}))

    # ── Chat (streaming) ──────────────────────────────────────────────

    async def _m_ingest_decide(self, rid: Any, params: dict, send: SendFn) -> None:
        """Approve|reject the pending ingest from the WinUI preview buttons (#663).

        ``params["decision"]`` is ``approve`` or ``reject``; for approve,
        ``params["edited_body"]`` carries the (possibly edited) preview text —
        NEVER routed as prompt text, so the raw article body stays out of
        sessions.db.  The reply is emitted as ONE informational ``token`` + ``end``
        frame (the same shape as the /approve reply), under the same fail-safe
        deadline as the ingest interception.  The ``end`` frame carries
        ``ingest_decided``: True when the pending slot is now cleared (the WinUI
        retires the preview buttons), False when it survives a transient failure
        (the buttons stay so the operator can retry).  getattr-guarded so a stub
        gateway without the surface returns a clean error frame.
        """
        session_id = params["session_id"]
        decision = str(params.get("decision", "approve"))
        edited_body = str(params.get("edited_body", ""))
        decide_handler = getattr(self._gateway, "handle_ingest_decision", None)
        if decide_handler is None:
            await send(error_response(
                rid, "unsupported",
                "Ingest decision is not available on this gateway.",
            ))
            return
        try:
            reply, decided = await asyncio.wait_for(
                decide_handler(session_id, decision, edited_body),
                timeout=self._prompt_stream_failsafe_s,
            )
        except asyncio.TimeoutError:
            logger.error(
                "_m_ingest_decide: %s timed out after %.0fs (session=%s) — "
                "emitting failsafe terminal frame",
                decision, self._prompt_stream_failsafe_s, session_id,
            )
            await send(stream_frame(rid, "token", {
                "token": (
                    "The decision timed out before the Orchestrator replied "
                    "(Fail-Closed). Retry it; a deterministic refusal will tell "
                    "you if it already took effect."
                ),
                "token_index": 0,
                "is_final": True,
                "is_tool_call": False,
                "session_id": session_id,
                "is_thinking": False,
            }))
            # Timed out → outcome unknown → treat as still-pending (keep buttons).
            await send(stream_frame(rid, "end", {
                "request_id": "", "informational": True, "failsafe": True,
                "ingest_decided": False,
            }))
            return
        await send(stream_frame(rid, "token", {
            "token": reply,
            "token_index": 0,
            "is_final": True,
            "is_tool_call": False,
            "session_id": session_id,
            "is_thinking": False,
        }))
        await send(stream_frame(rid, "end", {
            "request_id": "", "informational": True, "ingest_decided": bool(decided),
        }))

    async def _m_prompt(self, rid: Any, params: dict, send: SendFn) -> None:
        """Run a full conversational turn and stream the result.

        Emits ``token`` frames as the reply streams, then a ``pgov`` frame with
        the validator verdict, then an ``end`` frame. Persists the assistant
        turn exactly as the TUI does (approved -> approved row; denied ->
        denied row with reason codes), so both surfaces record identically.

        When ``params["speak"]`` is set and TTS is available, the reply is also
        synthesized **sentence-by-sentence as it streams** (ADR-017): completed
        sentences are pushed to a worker that emits ``audio`` frames concurrently
        with continued generation, so speech starts mid-reply instead of after
        it. This mirrors the screen's optimistic display — text/audio stream
        pre-validation — while tool-call tokens stay BUFFERED until PGOV clears
        them (unchanged). On a PGOV denial, an ``audio_cancel`` frame tells the
        front end to stop playback (already-spoken words cannot be retracted).

        Fail-safe guarantee (Vikunja #565):
        The entire streaming + PGOV + store arc runs under a
        ``_PROMPT_STREAM_FAILSAFE_S`` deadline. If the gateway stalls (e.g.
        GENERATION_COMPLETE never arrives), the arc is cancelled and a terminal
        ``end`` frame is still emitted, so the WinUI front end's text input is
        ALWAYS re-enabled within a bounded time regardless of what the gateway
        or Orchestrator does.
        """
        session_id = params["session_id"]
        prompt = params["prompt"]

        # ── Ingest / informational interception (#655 Stage B) ────────────
        # /ingest, /approve, /reject and the bare-URL nudge are handled by
        # the GATEWAY (deterministic tool output) before any AO prompt
        # dispatch.  The reply is emitted as ONE token frame (no per-token
        # streaming — the WinUI MarkdownBlock rebuilds its visual tree per
        # Markdown change, so a single frame renders an article-sized preview
        # in one rebuild) followed by the terminal ``end`` frame.  There is
        # deliberately NO pgov frame (the text was never PGOV-validated — the
        # front end's default verdict leaves the streamed text displayed) and
        # NO audio frames regardless of ``params["speak"]`` (informational
        # turns are never spoken).  getattr-guarded so stub/fake gateways
        # without the ingest surface keep the unchanged prompt arc.
        ingest_handler = getattr(self._gateway, "handle_ingest_command", None)
        if ingest_handler is not None:
            # Same fail-safe bound as the streaming arc: a stalled ingest IPC
            # call must never freeze the front end's input past the deadline
            # (the raw socket timeout alone is 180 s — too long for a UI).
            try:
                info_text = await asyncio.wait_for(
                    ingest_handler(session_id, prompt),
                    timeout=self._prompt_stream_failsafe_s,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "_m_prompt: ingest interception timed out after %.0fs "
                    "(session=%s) — emitting failsafe terminal frame",
                    self._prompt_stream_failsafe_s,
                    session_id,
                )
                await send(stream_frame(rid, "token", {
                    "token": (
                        "Ingest command timed out before the Orchestrator "
                        "replied (Fail-Closed). The operation may or may not "
                        "have completed — retry it; a deterministic refusal "
                        "will tell you if it already took effect."
                    ),
                    "token_index": 0,
                    "is_final": True,
                    "is_tool_call": False,
                    "session_id": session_id,
                    "is_thinking": False,
                }))
                await send(stream_frame(rid, "end", {
                    "request_id": "",
                    "informational": True,
                    "failsafe": True,
                }))
                return
            if info_text is not None:
                token_payload: dict[str, Any] = {
                    "token": info_text,
                    "token_index": 0,
                    "is_final": True,
                    "is_tool_call": False,
                    "session_id": session_id,
                    "is_thinking": False,
                }
                # Editable-preview attachment (#663 Workstream A): on the turn a
                # NEW ingest preview was created, carry the editable article body
                # (the cleaner's clean.text — not a fragile parse of the rendered
                # preview) + doc_uuid + source_type so the WinUI can offer
                # edit-before-approve.  getattr-guarded for stub gateways; the
                # gateway pops the signal so it never leaks onto a later turn.
                preview_meta_fn = getattr(self._gateway, "ingest_preview_meta", None)
                preview_meta = preview_meta_fn(session_id) if preview_meta_fn else None
                if preview_meta:
                    token_payload["ingest_preview"] = True
                    token_payload["ingest_doc_uuid"] = preview_meta.get("doc_uuid", "")
                    token_payload["ingest_source_type"] = preview_meta.get(
                        "source_type", ""
                    )
                    token_payload["ingest_editable_body"] = preview_meta.get(
                        "editable_body", ""
                    )
                await send(stream_frame(rid, "token", token_payload))
                await send(stream_frame(rid, "end", {
                    "request_id": "",
                    "informational": True,
                }))
                return

        # ── Dispatch interception (headless-coding, brief §9 — DORMANT) ──
        # /dispatch is handled by the GATEWAY (deterministic host-exec: enqueue to
        # the fleet, trigger a run, read the summary), emitted as ONE informational
        # token frame + a terminal end frame (same shape as imagine). getattr-
        # guarded; DORMANT-safe (disabled -> a clear notice, no subprocess).
        dispatch_handler = getattr(self._gateway, "handle_dispatch_command", None)
        if dispatch_handler is not None:
            try:
                disp_text = await asyncio.wait_for(
                    dispatch_handler(session_id, prompt),
                    timeout=self._imagine_failsafe_s,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "_m_prompt: dispatch interception timed out after %.0fs "
                    "(session=%s) — emitting failsafe terminal frame",
                    self._imagine_failsafe_s, session_id,
                )
                await send(stream_frame(rid, "token", {
                    "token": (
                        "The coding-dispatch command timed out before the "
                        "backend replied (Fail-Closed). Retry it."
                    ),
                    "token_index": 0,
                    "is_final": True,
                    "is_tool_call": False,
                    "session_id": session_id,
                    "is_thinking": False,
                }))
                await send(stream_frame(rid, "end", {
                    "request_id": "",
                    "informational": True,
                    "failsafe": True,
                }))
                return
            if disp_text is not None:
                disp_payload: dict[str, Any] = {
                    "token": disp_text,
                    "token_index": 0,
                    "is_final": True,
                    "is_tool_call": False,
                    "session_id": session_id,
                    "is_thinking": False,
                }
                # Attach Approve/Reject buttons to a plan preview (#712). getattr-
                # guarded + pop-on-read (the gateway pops it), so only the actual
                # plan-preview reply carries them — a status/reject/etc. does not.
                action_kind_fn = getattr(self._gateway, "dispatch_action_kind", None)
                action_kind = action_kind_fn(session_id) if action_kind_fn else ""
                if action_kind:
                    disp_payload["ui_actions"] = action_kind
                await send(stream_frame(rid, "token", disp_payload))
                await send(stream_frame(rid, "end", {
                    "request_id": "",
                    "informational": True,
                }))
                return

        # ── Imagine / image-gen interception (UC-010, ADR-033 — DORMANT) ──
        # /imagine, /edit, /save are handled by the GATEWAY (deterministic tool
        # output) before any AO prompt dispatch, emitted as ONE informational
        # token frame + a terminal end frame (no pgov, no audio — same shape as
        # the ingest interception).  getattr-guarded so stub gateways without
        # the imagine surface keep the unchanged prompt arc.  DORMANT-safe: with
        # image generation disabled the reply is the AO's "unavailable" notice.
        imagine_handler = getattr(self._gateway, "handle_imagine_command", None)
        if imagine_handler is not None:
            try:
                img_text = await asyncio.wait_for(
                    imagine_handler(session_id, prompt),
                    timeout=self._imagine_failsafe_s,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "_m_prompt: imagine interception timed out after %.0fs "
                    "(session=%s) — emitting failsafe terminal frame",
                    self._imagine_failsafe_s, session_id,
                )
                await send(stream_frame(rid, "token", {
                    "token": (
                        "Image command timed out before the Orchestrator "
                        "replied (Fail-Closed). Retry it."
                    ),
                    "token_index": 0,
                    "is_final": True,
                    "is_tool_call": False,
                    "session_id": session_id,
                    "is_thinking": False,
                }))
                await send(stream_frame(rid, "end", {
                    "request_id": "",
                    "informational": True,
                    "failsafe": True,
                }))
                return
            if img_text is not None:
                img_payload: dict[str, Any] = {
                    "token": img_text,
                    "token_index": 0,
                    "is_final": True,
                    "is_tool_call": False,
                    "session_id": session_id,
                    "is_thinking": False,
                }
                # Attach Edit/Save buttons to a successful image (#712). getattr-
                # guarded + pop-on-read, so a refusal / /images list / /save reply
                # (no NEW image) carries no buttons.
                image_meta_fn = getattr(self._gateway, "image_action_meta", None)
                image_meta = image_meta_fn(session_id) if image_meta_fn else None
                if image_meta and image_meta.get("image_id"):
                    img_payload["ui_actions"] = "image"
                    img_payload["ui_action_id"] = image_meta["image_id"]
                await send(stream_frame(rid, "token", img_payload))
                await send(stream_frame(rid, "end", {
                    "request_id": "",
                    "informational": True,
                }))
                return

        speak = (
            bool(params.get("speak"))
            and self._voice is not None
            and self._voice.tts_available
        )
        voice = params.get("voice")
        speed = params.get("speed")
        if speak:
            from services.voice.src.engine import extract_sentences as _extract_sentences

        request_id = await self._gateway.send_prompt(session_id, prompt)

        # Speech producer/consumer. The token loop pushes completed sentences onto
        # a queue; a worker synthesizes them and streams audio frames concurrently.
        sentence_q: asyncio.Queue[str | None] | None = asyncio.Queue() if speak else None
        cancel = asyncio.Event()
        worker = (
            asyncio.create_task(self._speak_worker(rid, send, sentence_q, cancel, voice, speed))
            if speak else None
        )
        buffer = ""

        # --- Fail-safe wrapper -------------------------------------------
        # _stream_arc does all the work. It is awaited inside wait_for so that
        # a stalled gateway cannot freeze the UI indefinitely. The finally block
        # below guarantees a terminal ``end`` frame is emitted on EVERY exit
        # path: normal completion, exception, and timeout (CancelledError).
        _terminal_emitted = False

        async def _stream_arc() -> None:
            nonlocal buffer

            async for token in self._gateway.stream_tokens(session_id):
                await send(stream_frame(rid, "token", token.to_dict()))
                if speak and not token.is_tool_call:
                    buffer += token.token
                    sentences, buffer = _extract_sentences(buffer)
                    for sentence in sentences:
                        await sentence_q.put(sentence)  # type: ignore[union-attr]

            pgov = self._gateway.get_pgov_result(request_id)

            if not pgov.approved:
                cancel.set()  # stop speaking unvalidated content immediately
                # Discard buffered tool-call tokens (Fail-Closed) and record denial.
                self._gateway.flush_tool_call_buffer(pgov_approved=False)
                if self._store is not None:
                    self._store.add_turn(
                        session_id, "assistant", pgov.sanitized_text,
                        "denied", list(pgov.reason_codes),
                    )
            else:
                for tc_token in self._gateway.flush_tool_call_buffer(pgov_approved=True):
                    await send(stream_frame(rid, "token", tc_token.to_dict()))
                if speak and buffer.strip():
                    await sentence_q.put(buffer.strip())  # type: ignore[union-attr]
                if self._store is not None:
                    self._store.add_turn(
                        session_id, "assistant",
                        pgov.sanitized_text or "(approved response)",
                        "approved", [],
                    )

            if speak:
                await sentence_q.put(None)  # type: ignore[union-attr] — sentinel: drain + exit
                if worker is not None:
                    await worker
                if not pgov.approved:
                    await send(stream_frame(rid, "audio_cancel", {}))

            await send(stream_frame(rid, "pgov", pgov.to_dict()))
            await send(stream_frame(rid, "end", {"request_id": request_id}))

        try:
            await asyncio.wait_for(_stream_arc(), timeout=self._prompt_stream_failsafe_s)
            _terminal_emitted = True
        except asyncio.TimeoutError:
            logger.error(
                "_m_prompt: stream arc timed out after %.0fs (session=%s request=%s) "
                "— emitting failsafe terminal frame (Vikunja #565)",
                self._prompt_stream_failsafe_s,
                session_id,
                request_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "_m_prompt: stream arc raised %s (session=%s request=%s) "
                "— emitting failsafe terminal frame",
                exc,
                session_id,
                request_id,
                exc_info=True,
            )
        finally:
            # Cancel the speak worker if it is still running (stall / exception).
            if worker is not None and not worker.done():
                cancel.set()
                worker.cancel()
            if not _terminal_emitted:
                # Emit the terminal ``end`` frame so the front end always
                # re-enables its text input. We do NOT emit a pgov frame here
                # because we may not have a valid result — the front end must
                # treat the absence of pgov as a degraded/stalled response.
                await send(stream_frame(rid, "end", {
                    "request_id": request_id,
                    "failsafe": True,
                }))

    async def _speak_worker(
        self, rid: Any, send: SendFn,
        sentence_q: "asyncio.Queue[str | None]", cancel: asyncio.Event,
        voice: Any, speed: Any,
    ) -> None:
        """Synthesize queued sentences and stream ``audio`` frames until sentinel."""
        from services.voice.src.audio import encode_b64_pcm

        index = 0
        while True:
            sentence = await sentence_q.get()
            if sentence is None:
                return
            if cancel.is_set():
                continue  # drain remaining sentences without speaking (post-denial)
            gen = self._voice.synthesize_stream(sentence, voice, speed)
            while not cancel.is_set():
                chunk = await asyncio.to_thread(_next_or_none, gen)
                if chunk is None:
                    break
                samples, sample_rate = chunk
                audio_b64 = await asyncio.to_thread(encode_b64_pcm, samples)
                await send(stream_frame(rid, "audio", {
                    "audio_b64": audio_b64, "sample_rate": sample_rate, "index": index,
                }))
                index += 1

    # ── Voice (ADR-017) ───────────────────────────────────────────────

    async def _m_voice_status(self, rid: Any, params: dict, send: SendFn) -> None:
        """Report which voice halves are available so the UI can gate affordances."""
        if self._voice is None:
            await send(ok_response(rid, {"stt": False, "tts": False, "voices": []}))
            return
        await send(ok_response(rid, self._voice.status()))

    async def _m_voice_set_stt(self, rid: Any, params: dict, send: SendFn) -> None:
        """Load (enabled=True) or unload (enabled=False) the STT model on demand (#660).

        The WinUI "Microphone (BlarAI listens)" toggle drives this: ON loads
        Whisper so the mic affordance lights up; OFF releases it to reclaim RAM
        (the operator's "quick use then quickly reclaim" intent + the
        100%-RAM-freeze history).  The (blocking) model load/unload runs off the
        event loop so the pipe stays responsive — a first toggle-on can take a few
        seconds.  Returns the refreshed :meth:`status` so the front end re-gates
        in one round-trip.  Fail-soft: with no engine, STT simply stays
        unavailable rather than erroring.
        """
        if self._voice is None:
            await send(ok_response(rid, {"stt": False, "tts": False, "voices": []}))
            return
        enabled = bool(params.get("enabled"))
        if enabled:
            await asyncio.to_thread(self._voice.load_stt)
        else:
            await asyncio.to_thread(self._voice.unload_stt)
        await send(ok_response(rid, self._voice.status()))

    async def _m_voice_set_tts(self, rid: Any, params: dict, send: SendFn) -> None:
        """Load (enabled=True) or unload (enabled=False) the TTS model on demand (#660).

        The WinUI "Voice replies (BlarAI speaks)" toggle drives this: ON loads
        Kokoro so replies can be spoken; OFF releases it (and its 54-voice bank)
        to reclaim RAM.  Same off-the-event-loop + refreshed-status posture as
        :meth:`_m_voice_set_stt`.
        """
        if self._voice is None:
            await send(ok_response(rid, {"stt": False, "tts": False, "voices": []}))
            return
        enabled = bool(params.get("enabled"))
        if enabled:
            await asyncio.to_thread(self._voice.load_tts)
        else:
            await asyncio.to_thread(self._voice.unload_tts)
        await send(ok_response(rid, self._voice.status()))

    async def _m_transcribe(self, rid: Any, params: dict, send: SendFn) -> None:
        """Decode a base64 PCM utterance and return its transcription.

        The text is NOT auto-submitted here; the front end drives the normal
        ``prompt`` path with it, so speech input passes through PGOV and the full
        governance path exactly like typed input (ADR-017 §2.5).
        """
        if self._voice is None or not self._voice.stt_available:
            _voice_log("transcribe: REJECTED — voice/STT unavailable")
            await send(error_response(rid, "voice_unavailable", "Speech-to-text is not available"))
            return
        from services.voice.src.audio import prepare_for_stt

        audio_b64 = params["audio_b64"]
        sample_rate = int(params.get("sample_rate", 16000))
        fmt = params.get("format", "pcm_s16le")
        channels = int(params.get("channels", 1))
        _voice_log(f"transcribe: recv b64_len={len(audio_b64)} sr={sample_rate} ch={channels} fmt={fmt}")

        try:
            samples = await asyncio.to_thread(
                prepare_for_stt, audio_b64, sample_rate, fmt, channels
            )
            _voice_log(f"transcribe: prepared {len(samples)} samples; running whisper…")
            text = await asyncio.to_thread(self._voice.transcribe, samples)
            _voice_log(f"transcribe: result={text!r}")
        except Exception as exc:  # noqa: BLE001 — log then re-raise to the error frame
            _voice_log(f"transcribe: EXCEPTION {type(exc).__name__}: {exc}")
            raise
        await send(ok_response(rid, {"text": text}))

    async def _m_synthesize(self, rid: Any, params: dict, send: SendFn) -> None:
        """Stream synthesized audio chunks for *text* (one frame per sentence)."""
        if self._voice is None or not self._voice.tts_available:
            await send(error_response(rid, "voice_unavailable", "Text-to-speech is not available"))
            return
        from services.voice.src.audio import encode_b64_pcm

        text = params["text"]
        voice = params.get("voice")
        speed = params.get("speed")  # None -> engine default pace

        # The engine generator is synchronous (blocking model calls); pull each
        # chunk on a worker thread so the pipe event loop keeps streaming.
        gen = self._voice.synthesize_stream(text, voice, speed)
        index = 0
        while True:
            chunk = await asyncio.to_thread(_next_or_none, gen)
            if chunk is None:
                break
            samples, sample_rate = chunk
            audio_b64 = await asyncio.to_thread(encode_b64_pcm, samples)
            await send(stream_frame(rid, "audio", {
                "audio_b64": audio_b64,
                "sample_rate": sample_rate,
                "index": index,
            }))
            index += 1
        await send(stream_frame(rid, "end", {"chunks": index}))

    # ── Image display-resolve (UC-010/UC-003 WS3, ADR-033 §D) ──────────────

    #: Named-pipe resolve chunk size (raw bytes pre-base64).  Sized so a
    #: base64 chunk + the small JSON envelope stays well under the pipe's
    #: 4 MB frame cap (``protocol.MAX_FRAME_BYTES``) — the pipe leg is far
    #: roomier than the 64 KB vsock leg, but chunking keeps the C# reassembly
    #: contract uniform and the per-frame memory bounded.
    _RESOLVE_PIPE_CHUNK_BYTES: int = 256 * 1024

    #: Authoritative ``blarai-img://`` id shape — 32 lowercase hex (uuid4().hex),
    #: anchored full-string (the ADR-032 Am.1 lesson: ``\Z`` not ``$``).
    _RESOLVE_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")

    async def _m_resolve_image(self, rid: Any, params: dict, send: SendFn) -> None:
        """Resolve a ``blarai-img://<id>`` to bytes and stream them to the WinUI.

        The WinUI ``ImageResolver`` decrypt seam (UC-010/UC-003 WS3, ADR-033 §D):
        given an ``image_id``, drive the gateway's resolve reader (which reaches
        the AO-resident encrypted store over vsock) and stream the decrypted PNG
        back as ``kind="chunk"`` frames (``{data_b64, mime}``; ``mime`` on the
        first chunk) terminated by ``kind="end"`` ``{found: bool}``.  The C# side
        reassembles the chunks and renders null when ``found`` is false or no data
        arrived.

        Fail-Closed: a malformed id, an unknown id, a decrypt-quarantine, a
        dormant store, or any transport failure ALL produce a clean
        ``end{found:false}`` with NO chunk frames — never an error frame, never
        partial plaintext.  Bytes are streamed straight through; nothing is
        written to disk or a log on this path.
        """
        image_id = str(params.get("image_id", "")).strip()
        # Validate the id shape up front — a forged / malformed ref never reaches
        # the resolve leg (it would resolve to None anyway, but a cheap gate keeps
        # the corridor strict and matches the host-internal resolver's id guard).
        if not self._RESOLVE_ID_RE.match(image_id):
            await send(stream_frame(rid, "end", {"found": False}))
            return

        try:
            resolved = await asyncio.to_thread(
                self._gateway._resolve_generated_image, image_id
            )
        except Exception as exc:  # noqa: BLE001 — Fail-Closed: any error -> not-found
            cid = secrets.token_hex(4)
            logger.error(
                "resolve_image failed [cid=%s] for id=%s: %s",
                cid, image_id, exc, exc_info=True,
            )
            await send(stream_frame(rid, "end", {"found": False}))
            return

        if resolved is None:
            await send(stream_frame(rid, "end", {"found": False}))
            return

        mime, data = resolved
        if not data:
            # A found image with empty bytes is treated as absent for display.
            await send(stream_frame(rid, "end", {"found": False}))
            return

        chunk = self._RESOLVE_PIPE_CHUNK_BYTES
        first = True
        for start in range(0, len(data), chunk):
            piece = data[start : start + chunk]
            value: dict[str, Any] = {"data_b64": base64.b64encode(piece).decode("ascii")}
            if first:
                value["mime"] = mime
                first = False
            await send(stream_frame(rid, "chunk", value))
        await send(stream_frame(rid, "end", {"found": True}))

    # ── Generated-image management (UC-010 Phase 2 gallery, #668) ──────────
    #
    # The WinUI gallery pane lists and manages the born-encrypted generated
    # images (UC-010).  Both legs are NON-STREAMING (a single ok_response) and
    # METADATA-ONLY on the wire: the list carries per-image metadata (id, mime,
    # byte_size from a ``length(data)`` aggregate — NEVER a decrypt) and manage
    # carries only an outcome dict.  Decrypted PIXELS cross ONLY via the separate
    # ``resolve_image`` corridor above (display) or the operator's explicit
    # ``/save`` export — never on these two legs.  Both delegate to the SAME
    # gateway transport legs the ``/images`` chat command already uses
    # (``_list_generated_images`` / ``_manage_generated_image``,
    # services/ui_gateway/src/transport.py), so the gallery is a second front-end
    # over a proven Phase-1 backend with no new AO surface.

    #: The two management actions the manage leg accepts.  Anything else is a
    #: BAD_REQUEST refused BEFORE the gateway is consulted (fail-closed), so a
    #: malformed action never reaches the born-encrypted store.
    _MANAGE_ACTIONS = frozenset({"delete", "mark_saved"})

    async def _m_list_generated_images(self, rid: Any, params: dict, send: SendFn) -> None:
        """List generated-image METADATA for the WinUI gallery (UC-010 #668).

        Optional ``params["session_id"]`` filters to one chat (empty / missing →
        all images).  Delegates to the gateway's ``_list_generated_images`` leg
        (IMAGE_LIST over vsock), which returns ``{images, total, truncated}``
        (capped server-side, with ``truncated`` set when the cap clipped the
        list) — or a Fail-Closed ``{images: [], total: 0, truncated: False,
        error: ...}`` shape on any transport failure.

        METADATA ONLY: no image bytes / prompts ever cross this leg.  Fail-Closed
        in every direction — a stub gateway without the leg, or ANY exception,
        yields a clean empty result (NEVER an error frame, NEVER a raise): an
        empty gallery is the safe degraded state.
        """
        session_id = str(params.get("session_id", "")).strip() or None
        empty: dict[str, Any] = {"images": [], "total": 0, "truncated": False}
        lister = getattr(self._gateway, "_list_generated_images", None)
        if lister is None:
            # Older / stub gateway without the management legs — degrade to an
            # empty gallery rather than surfacing an error to the operator.
            await send(ok_response(rid, empty))
            return
        try:
            # The gateway leg is ``async def`` — await it DIRECTLY.  NOT
            # ``asyncio.to_thread`` (the pattern ``_m_resolve_image`` uses for the
            # SYNC ``_resolve_generated_image``): to_thread on an async fn runs it in
            # a worker thread and returns the UN-AWAITED coroutine, which then fails
            # JSON encoding ("coroutine is not JSON serializable") and fail-closes the
            # gallery to empty (#668 live-verify fix).
            result = await lister(session_id)
        except Exception as exc:  # noqa: BLE001 — Fail-Closed: any error -> empty
            cid = secrets.token_hex(4)
            logger.error(
                "list_generated_images failed [cid=%s]: %s", cid, exc, exc_info=True
            )
            await send(ok_response(rid, empty))
            return
        await send(ok_response(rid, result))

    async def _m_manage_generated_image(self, rid: Any, params: dict, send: SendFn) -> None:
        """Delete / mark-saved a generated image by id for the gallery (UC-010 #668).

        ``params["action"]`` ∈ {``delete``, ``mark_saved``}; ``params["image_id"]``
        is a ``uuid4().hex`` (32 lowercase hex).  Both are validated UP FRONT:
        an unknown action OR an id failing the anchored ``\\A[0-9a-f]{32}\\Z`` gate
        is refused with a Fail-Closed ``ok=False`` BAD_REQUEST result and the
        gateway is NEVER consulted — a forged / malformed delete request can never
        reach the born-encrypted store (the same id-gate discipline as
        ``_m_resolve_image``).  A well-formed request delegates to the gateway's
        ``_manage_generated_image`` leg (IMAGE_MANAGE over vsock), which returns
        the IMAGE_MANAGE_RESULT ``{ok, action, image_id, found, ...}`` (or a
        Fail-Closed ``ok=False`` shape on transport failure).

        METADATA ONLY: no image bytes cross this leg.  Fail-Closed — a stub
        gateway or ANY exception yields a clean ``ok=False`` result, never a raise.
        """
        action = str(params.get("action", "")).strip()
        image_id = str(params.get("image_id", "")).strip()

        def _bad_request(message: str) -> dict[str, Any]:
            return {
                "ok": False, "action": action, "image_id": image_id,
                "found": False, "error_code": "BAD_REQUEST", "message": message,
            }

        # Validate action + id BEFORE touching the gateway (fail-closed): a bad
        # action or a forged id is refused without ever reaching the store.
        if action not in self._MANAGE_ACTIONS:
            await send(ok_response(rid, _bad_request(
                f"Unsupported image action: {action!r}."
            )))
            return
        if not self._RESOLVE_ID_RE.match(image_id):
            await send(ok_response(rid, _bad_request(
                "Malformed image id (expected 32 lowercase hex)."
            )))
            return

        manager = getattr(self._gateway, "_manage_generated_image", None)
        if manager is None:
            await send(ok_response(rid, {
                "ok": False, "action": action, "image_id": image_id,
                "found": False, "error_code": "UNSUPPORTED",
                "message": "Image management is not available on this gateway.",
            }))
            return
        try:
            # async gateway leg — await DIRECTLY, never asyncio.to_thread (which
            # would return an un-awaited coroutine; see _m_list_generated_images).
            result = await manager(action, image_id)
        except Exception as exc:  # noqa: BLE001 — Fail-Closed: any error -> ok=False
            cid = secrets.token_hex(4)
            logger.error(
                "manage_generated_image %s failed [cid=%s]: %s",
                action, cid, exc, exc_info=True,
            )
            await send(ok_response(rid, {
                "ok": False, "action": action, "image_id": image_id,
                "found": False, "error_code": "INTERNAL_ERROR",
                "message": f"internal error [{cid}]",
            }))
            return
        await send(ok_response(rid, result))
