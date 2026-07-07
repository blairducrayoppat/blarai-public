#!/usr/bin/env python
"""Regenerate SPEAKER_NOTES.md from fable5_deck.html (the single source of truth)."""
import pathlib
import re

D = pathlib.Path(__file__).resolve().parent
t = (D / "fable5_deck.html").read_text(encoding="utf-8")

sections = re.findall(
    r"<!-- (\d+) [^>]*?-->.*?<h[12][^>]*>(.*?)</h[12]>.*?"
    r'<aside class="notes">(.*?)</aside>',
    t, re.S)

out = ["# Speaker notes — Directing the Machine (generated; edit the HTML, then rerun extract_notes.py)", ""]
total = 0
for num, head, notes in sections:
    head = re.sub(r"<[^>]+>", " ", head)
    head = re.sub(r"\s+", " ", head).strip()
    body = re.sub(r"\s+", " ", notes).strip()
    w = len(body.split())
    total += w
    out += [f"## Slide {num} — {head}  *({w} words)*", "", body, ""]
out += [f"---", f"**Total: {total} words ≈ {total/145:.1f}–{total/130:.1f} min at 145–130 wpm (+ ~1 min transitions).**", ""]
(D / "SPEAKER_NOTES.md").write_text("\n".join(out), encoding="utf-8")
print(f"SPEAKER_NOTES.md written: {len(sections)} slides, {total} words")
