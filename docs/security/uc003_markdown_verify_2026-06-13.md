# UC-003 Markdown-Structure Verification — guest parse, no egress (2026-06-13)

**Result:** GREEN. `include_formatting=True` (`services/cleaner/src/extraction.py`)
is confirmed LIVE inside the re-provisioned guest parser, proven end-to-end over the
AF_HYPERV vsock parse channel. **No egress** — host→guest parse of a local fixture;
`guarded_fetch` / the URL adjudicator / `egress_guard` untouched, fetch limb dormant.

**Relates to:** Vikunja #662 (guest code-update channel), #655 (UC-003 program),
ADR-030 §3 (guest-homed parsing), `docs/security/uc003_live_fetch_proof_2026-06-12.md`
(the prior round-trip proof — that one fetched; this one deliberately does not).

---

## What was verified

The UC-003 STEP 1 change adds document structure (headings, lists, inline bold) to
extracted article text. It reaches the host pipeline (paste/file ingest) directly, but
the **guest-homed parser** (URL ingest, running inside the NIC-less Alpine guest) carries
its own baked-in copy of `extraction.py`. After re-provisioning the guest from the
rebuilt CD ISO (#662), this check confirms the flag is live on the guest side too.

## Method (egress-free, production-faithful transport)

`scripts/uc003_markdown_verify.py`, run under the 3.11 runtime venv. A heading/list/bold
HTML fixture is encoded into an `INGEST_PARSE_REQUEST` and sent over the parse channel via
the production version bridge (py-3.14 subprocess, since 3.11 lacks `socket.AF_HYPERV`) —
the same transport path as the 2026-06-12 live-fetch proof. The returned cleaned text is
scanned for the formatting markers the old (flag-off) code stripped.

- **No fetch.** The fixture is bytes the process already holds. No `guarded_fetch`, no URL
  adjudicator registration, no `egress_guard` arming. The welded egress door and the #659
  locks are not touched.
- Endpoint: `vm_id=9c7f986f-7afd-48b0-af5b-2c330df6b38f`,
  `service_guid=0000c351-facb-11e6-bd58-64006a7986d3`, vsock port `50001`.

## Result

```
guest parse ok: status=clean, word_count=212, confidence=1.000
list dash marker (- ) : True
inline bold (**)      : True
heading hash (#)      : True
```

Returned cleaned text (excerpt):

```
# Markdown Structure Verification

This document exists to confirm that the BlarAI guest-homed parser preserves document
structure when it extracts an article. ...

## Why structure matters

A knowledge bank that flattens every heading into indistinguishable prose loses the shape
of the source. ... the emphasis an author placed on a **critical warning** are part of the
meaning, not decoration. ...

## What this fixture checks

...

- First, that unordered list items keep their dash markers intact.
- Second, that multiple list entries each stay on their own line.
- Third, that the list is not collapsed into one flat paragraph.
```

Machine-readable evidence: `docs/security/uc003_markdown_verify_2026-06-13.json`.

## Significance

- Markdown ATX headings (`#`, `##`), inline bold (`**`), and dash list markers all survive
  guest extraction. WinUI routes every assistant message through `MarkdownBlock.cs`, so
  this text renders as structured content with no UI change.
- UC-003 STEP 1 (headers/structure) is now complete end-to-end: host pipeline + guest
  parser both carry the flag, the guest path verified on the real vsock boundary.
- STEP 2 (images) and any future guest change use the #662 CD-ISO re-provision runbook
  (`docs/security/guest_parser_provisioning_record.md` §3) followed by this verification.
