"""
Integration: end-to-end PDF /load path.

Generates a real PDF in a temp userdata/ directory, exercises the full
chain — gateway.load_document() → pending buffer → encode_prompt_request
→ AO _handle_prompt_request → ContextManager.add_grounded_context —
and asserts the PDF's extracted text reaches the grounded context with
the spotlighting delimiters + datamarking applied.

This is the test that would have caught silent regressions in any of the
five layers: pypdf install, document_loader extension routing,
extraction guards, IPC field plumbing, and AO grounded-chunk wiring.
The unit tests in services/ui_gateway/tests and
services/assistant_orchestrator/tests cover each layer in isolation;
this test proves they compose.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pypdf
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from shared.ipc.protocol import MessageFramer
from shared.ipc.vsock import VsockAddress, VsockConfig
from services.assistant_orchestrator.src.context_manager import (
    CONTEXT_BEGIN,
    CONTEXT_END,
)
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorEntrypointConfig,
    AssistantOrchestratorService,
)
from services.ui_gateway.src.document_loader import load_document


def _write_simple_pdf(path: Path, pages_text: list[str]) -> None:
    """Write a minimal PDF with text-bearing pages via pypdf's writer.

    Same helper as services/ui_gateway/tests/test_document_loader.py —
    duplicated here intentionally so the integration test is self-
    contained and the fixture path is auditable in one file.
    """
    writer = pypdf.PdfWriter()
    for text in pages_text:
        page = writer.add_blank_page(width=595, height=842)
        content = (
            f"BT /F1 12 Tf 72 750 Td ({text.replace('(', '').replace(')', '')}) Tj ET"
        )
        stream = DecodedStreamObject()
        stream.set_data(content.encode("latin-1"))
        page[NameObject("/Contents")] = stream
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }),
            }),
        })
    with open(path, "wb") as fh:
        writer.write(fh)


class _FakeTransport:
    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


def _make_ao_service() -> AssistantOrchestratorService:
    from services.assistant_orchestrator.src.context_manager import ContextManager

    config = AssistantOrchestratorEntrypointConfig(
        model_dir=Path("models"),
        manifest_path=None,
        device="GPU",
        priority=1,
        draft_model_dir=None,
        speculative_decoding_enabled=False,
        max_new_tokens=64,
        generation_temperature=0.0,
        generation_top_k=50,
        generation_top_p=0.9,
        generation_repetition_penalty=1.1,
        generation_do_sample=False,
        response_depth_mode="standard",
        dev_mode=True,
        jwt_ca_cert_path=None,
        vsock_config=VsockConfig(address=VsockAddress(cid=0, port=0)),
        pgov_cosine_threshold=0.85,
        deployment_mode="host",  # type: ignore[arg-type]
    )
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = config
    service._context_manager = ContextManager()
    return service


@patch("services.assistant_orchestrator.src.entrypoint.validate_output")
def test_pdf_load_grounds_ao_context(
    mock_validate: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a PDF dropped into userdata/ ends up as a grounded
    chunk inside the AO ContextManager, wrapped in spotlighting
    delimiters and prefixed with a datamarking header.
    """
    # ---- Stage 1: synthesize a real PDF in a fake userdata/ -----
    import services.ui_gateway.src.document_loader as dl_mod

    monkeypatch.setattr(dl_mod, "USERDATA_DIR", tmp_path)
    pdf_path = tmp_path / "lab_results.pdf"
    _write_simple_pdf(pdf_path, [
        "Patient: J. Doe",
        "Hemoglobin: 14.2 g/dL",
    ])

    # ---- Stage 2: gateway load_document extracts text -----
    doc = load_document("lab_results.pdf")
    assert doc["filename"] == "lab_results.pdf"
    assert "Hemoglobin" in doc["content"]
    assert "J. Doe" in doc["content"]

    # ---- Stage 3: AO receives the doc via PROMPT_REQUEST -----
    mock_validate.side_effect = lambda generated_text, **_kw: SimpleNamespace(
        approved=True, sanitized_text=generated_text,
    )
    service = _make_ao_service()
    service._inference = MagicMock()
    service._inference.generate_text.return_value = SimpleNamespace(
        text="Your hemoglobin is 14.2 g/dL.",
        token_count=8,
        error=None,
    )

    framer = MessageFramer()
    request = framer.encode_prompt_request(
        session_id="pdf-e2e",
        prompt="What's my hemoglobin?",
        request_id="r1",
        documents=[{"filename": doc["filename"], "content": doc["content"]}],
    )
    service._handle_connection(_FakeTransport(request))

    # ---- Stage 4: ContextManager has the grounded chunk -----
    ctx = service._context_manager._sessions.get("pdf-e2e")
    assert ctx is not None, "AO must have created the session"
    assert len(ctx.grounded_chunks) == 1, (
        f"Expected exactly one grounded chunk, got {len(ctx.grounded_chunks)}"
    )
    grounded = ctx.grounded_chunks[0]
    # Spotlighting boundary present
    assert CONTEXT_BEGIN in grounded
    assert CONTEXT_END in grounded
    # Datamarking applied — every chunk gets a per-load random marker
    assert "<|DOC-" in grounded
    # PDF's actual extracted text reached the model's context
    assert "Hemoglobin" in grounded
    assert "J. Doe" in grounded
