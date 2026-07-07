# BlarAI userdata/

Place your documents here to load them into BlarAI sessions.

## Usage

1. Copy a `.txt`, `.md`, or `.pdf` file into this folder.
2. In the BlarAI chat, type `/load <filename>` (e.g. `/load notes.txt` or `/load tax_2025.pdf`).
3. BlarAI confirms the load and you can ask questions about the file's contents.

The loaded document is available for the rest of that chat session.
Starting a new session (Ctrl+N) clears loaded documents. Type `/unload`
in the chat to clear them mid-session.

## Constraints

- Accepted formats: `.txt`, `.md`, `.pdf`.
- Maximum file size:
  - `.txt` / `.md`: **16 KB on disk** (file size = content size).
  - `.pdf`: **1 MB on disk**, with extracted text capped at **16 KB**.
    Longer PDFs are loaded but text beyond the cap is truncated with a
    visible `[...truncated...]` marker so you and the assistant both
    know the document was cut off.
- PDF support reads **text-based PDFs only**. Scanned-image PDFs (no
  embedded text) are rejected with an OCR-not-supported message.
  Password-protected PDFs are rejected — save an unencrypted copy.
- Files must reside directly in this folder — subdirectory paths are
  not allowed.

## Security note

Loaded documents are untrusted content. BlarAI applies input-side
prompt-injection hardening: forged internal framing tokens are neutralized so
a document cannot break out of its data region, and document content is
scanned for known injection phrasings — if any are found, the load
confirmation shows a warning.

This is defense-in-depth, not a guarantee. A novel injection that uses no
known phrasing could still influence the assistant. **Prefer to load documents
you trust, and treat answers about a flagged document with extra care.**

## Privacy note

The contents of this folder are **gitignored** and will never be committed to version control.
Your private documents stay on your machine.
