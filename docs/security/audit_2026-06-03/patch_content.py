#!/usr/bin/env python
"""Apply the content cross-check's clarity fixes (deck verified FAITHFUL; these are
non-expert clarity improvements, not accuracy corrections). Append targeted
clarifying bullets, then re-run build_deck.py.
"""
import json
import pathlib

D = pathlib.Path(__file__).resolve().parent
deck = json.loads((D / "deck_outline.json").read_text(encoding="utf-8"))

PATCHES = [
    ("privacy & network",
     "Nuance (important): those ~270 network packages are PRESENT and loaded in the "
     "process, but NO runtime code CALLS them — egress is blocked by code discipline, "
     "not by a guard. There is no active network today; the boundary is one regression "
     "or one injection away, with nothing in code to stop it. That is why a "
     "code-enforced egress kill-switch is a Tier-0 fix."),
    ("architecture overview",
     "The Hyper-V VM is a REAL, working isolation + file-transfer boundary — it is "
     "simply started EMPTY today (the security-critical code runs in the host process, "
     "not inside it). It is not vestigial: it could later hold the network-facing "
     "services so untrusted web content is contained, once its isolation is enforced."),
    ("worst default",
     "Why it is the worst: one config choice — deployment_mode=guest — collapses "
     "MULTIPLE controls at once (mTLS, identity binding, weight verification, measured "
     "boot). A single switch with whole-perimeter blast radius."),
]

for key, bullet in PATCHES:
    for s in deck["slides"]:
        if key in s.get("title", "").lower():
            s.setdefault("bullets", []).append(bullet)
            print("patched:", s["title"][:50])
            break
    else:
        print("NO MATCH:", key)

(D / "deck_outline.json").write_text(json.dumps(deck, indent=2), encoding="utf-8")
print("done")
