#!/usr/bin/env python
"""Build the two standalone 13-year-old explainer decks (#644).

Source seeds: docs/security/capstone_explainers/{attestation,host_guest_secure_dataflow}.md.
Same pipeline + look-and-feel as the main #612 capstone deck (self-contained HTML, local
mermaid.min.js, keyboard-nav, render-API diagram embedding). One deck per explainer; the
in-deck 2-slide versions in the capstone stay. 13-year-old surface + accurate mechanism
underneath, keeping the seeds' built-vs-designed honesty (host-mode default vs VM-guest #615;
security-material attestation vs PCR measured-boot #627).

Mermaid is authored in triple-quoted strings (real newlines, quoted labels) so the emitted
JSON is correct-by-construction. Emits, per explainer: <name>_outline.json (diagram source for
_validate) + <name>.html. Run:  python make_explainers.py
"""
import html
import json
import pathlib

D = pathlib.Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Diagrams (conservative mermaid: every label quoted, real newlines, balanced).
# ---------------------------------------------------------------------------

ATTEST = """flowchart TD
  Boot["A service boots"] --> Gate{"Attestation gate<br/>(security-material check)"}
  Gate --> A["Model weights match the<br/>TPM-signed manifest (fingerprint + signature)"]
  Gate --> B["Decision-signing key present in the TPM"]
  Gate --> C["Per-boot certificate authority present"]
  A --> Q{"All checks valid?"}
  B --> Q
  C --> Q
  Q -->|"Yes"| Run["Start serving requests"]
  Q -->|"No — any single check fails"| Stop["REFUSE to start<br/>hard-lock after 3 tries"]
  TPM["TPM 2.0 chip<br/>its keys can never be copied out"] -. "signs and verifies the manifest" .-> A
"""

HOSTGUEST = """flowchart LR
  subgraph HOST["Windows Host (today's default)"]
    GW["UI Gateway"]
  end
  subgraph GUEST["Hyper-V Guest VM (Alpine) — NO network card (#615)"]
    AO["Assistant Orchestrator"]
  end
  GW <==>|"the vsock hatch:<br/>built by the hypervisor, not the network"| AO
"""

# ---------------------------------------------------------------------------
# Render machinery (mirrors the main deck's build_deck.py look-and-feel).
# ---------------------------------------------------------------------------

def esc(s):
    return html.escape(str(s if s is not None else ""))


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script src="mermaid.min.js"></script>
<style>
:root{--bg:#0d1117;--fg:#e6edf3;--ac:#58a6ff;--mut:#8b949e;--card:#161b22;--bd:#30363d}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif}
#deck{height:100vh;width:100vw;overflow:hidden;position:relative}
.slide{display:none;flex-direction:column;justify-content:center;height:100vh;width:100vw;padding:4.5vh 7vw 8vh;overflow-y:auto}
.slide.active{display:flex}
.slide[data-type=section],.slide[data-type=title]{align-items:center;text-align:center}
.titlebox h1{font-size:2.5rem;max-width:24ch;line-height:1.15;margin:.1em auto}
.subtitle{font-size:1.25rem;color:var(--ac);max-width:66ch;margin:.4em auto}
.meta{color:var(--mut);font-size:.95rem;max-width:70ch;margin:.6em auto}
h2{font-size:1.8rem;color:var(--ac);margin:0 0 .5em;border-bottom:2px solid var(--bd);padding-bottom:.3em}
ul{font-size:1.2rem;line-height:1.6;max-width:84ch}li{margin:.4em 0}
.lede{font-size:1.22rem;color:var(--fg);max-width:84ch;margin:.2em 0 .7em;line-height:1.5}
.slide[data-type=section] h2{font-size:2.2rem;border:0;color:var(--fg)}
.mmd{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:1.1em;margin-top:.7em;text-align:center;max-width:94ch;overflow-x:auto}
.mmd svg{max-width:100%;height:auto}
.mmdwait{color:var(--mut)}.mmderr{color:#ff6b6b;text-align:left;white-space:pre-wrap;font-family:monospace}
#bar{position:fixed;bottom:0;left:0;right:0;display:flex;justify-content:space-between;align-items:center;padding:.5em 1.2em;background:#010409cc;border-top:1px solid var(--bd);font-size:.85rem;color:var(--mut)}
#bar b{color:var(--ac)}
kbd{background:var(--card);border:1px solid var(--bd);border-radius:4px;padding:.1em .4em}
</style></head><body>
<div id="deck">__SLIDES__</div>
<div id="bar"><span>__BAR__</span><span><kbd>&larr;</kbd> <kbd>&rarr;</kbd> navigate &middot; <b><span id="cur">1</span></b>/<span id="tot">1</span></span></div>
<script>
const MMD = __MMD__;
mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'loose',flowchart:{useMaxWidth:true}});
(async () => {
  for (const [id, code] of MMD) {
    const host = document.getElementById(id);
    if (!host) continue;
    try { const { svg } = await mermaid.render(id + '_svg', code); host.innerHTML = svg; }
    catch (e) { host.innerHTML = '<div class="mmderr">Diagram failed to render:\\n' + (e && e.message ? e.message : e) + '</div>'; }
  }
})();
const S=[...document.querySelectorAll('.slide')];let i=0;
document.getElementById('tot').textContent=S.length;
function show(n){i=Math.max(0,Math.min(S.length-1,n));S.forEach((s,k)=>s.classList.toggle('active',k===i));document.getElementById('cur').textContent=i+1;history.replaceState(null,'',' #'+(i+1))}
addEventListener('keydown',e=>{if(['ArrowRight','PageDown',' '].includes(e.key)){show(i+1);e.preventDefault()}if(['ArrowLeft','PageUp'].includes(e.key)){show(i-1);e.preventDefault()}});
show((parseInt(location.hash.slice(1))||1)-1);
</script></body></html>"""


def render_deck(deck):
    diagrams = []

    def diagram(code):
        if not code or not code.strip():
            return ""
        did = "mmd%d" % len(diagrams)
        diagrams.append([did, code])
        return f'<div class="mmd" id="{did}"><span class="mmdwait">rendering diagram…</span></div>'

    slides = []

    def add(inner, stype="content"):
        slides.append(f'<section class="slide" data-type="{esc(stype)}">{inner}</section>')

    add(
        f'<div class="titlebox"><h1>{esc(deck["title"])}</h1>'
        f'<p class="subtitle">{esc(deck.get("subtitle"))}</p>'
        f'<p class="meta">{esc(deck.get("meta"))}</p></div>',
        "title",
    )
    for s in deck["slides"]:
        t = s.get("type", "content")
        body = f'<h2>{esc(s["title"])}</h2>'
        if s.get("lede"):
            body += f'<p class="lede">{esc(s["lede"])}</p>'
        if s.get("bullets"):
            body += "<ul>" + "".join(f"<li>{esc(b)}</li>" for b in s["bullets"]) + "</ul>"
        if s.get("mermaid"):
            body += diagram(s["mermaid"])
        add(body, "section" if t == "section" else t)

    out = (
        TEMPLATE.replace("__TITLE__", esc(deck["title"]))
        .replace("__BAR__", esc(deck.get("bar", deck["title"])))
        .replace("__SLIDES__", "\n".join(slides))
        .replace("__MMD__", json.dumps(diagrams))
    )
    return out, diagrams


# ---------------------------------------------------------------------------
# The two explainer decks.
# ---------------------------------------------------------------------------

ATTESTATION_DECK = {
    "title": "Attestation — How BlarAI Proves It’s Really Itself, Before It Runs",
    "subtitle": "A plain-language explainer (the 13-year-old version first, then the real mechanism) of BlarAI’s boot-time trust check.",
    "meta": "Grounded in ADR-028 (attestation scope) + ADR-018 (TPM trust root); shared/models/weight_integrity.py. Companion to the #612 capstone deck.",
    "bar": "BlarAI Explainer — Attestation",
    "slides": [
        {
            "type": "content",
            "title": "The Picture — the Morning Vault Inspection",
            "lede": "Attestation = proving the system is genuinely ITSELF and UNMODIFIED before it is trusted to run.",
            "bullets": [
                "Before the vault opens each morning, a trusted inspector runs three checks — and if ANY one fails, the vault refuses to open (and after three failed tries, it locks down completely).",
                "1) Are the precious documents real? Every model-weight file (the AI’s “brain”) has a unique fingerprint. The inspector recomputes each fingerprint and compares it to a sealed master list (the “manifest”). One altered file ⇒ mismatch ⇒ stop.",
                "2) Is the master list itself genuine? The list is stamped with a wax seal that can only be made by a stamp locked inside a tamper-proof safe (the TPM chip) — and that stamp can never leave the safe. So even an attacker who swaps a document AND rewrites the list can’t forge the seal. The inspector checks the seal BEFORE reading the list.",
                "3) Are the master keys and the ID-card printer present? The key that signs BlarAI’s security decisions lives in the TPM safe, and the authority that issues the ID badges is present.",
            ],
            "speaker_notes": "The spoken kid-level version, from the attestation seed §1.",
        },
        {
            "type": "diagram",
            "title": "The Boot-Time Trust Check",
            "lede": "The TPM is a tamper-proof safe whose keys never leave it. At boot, BlarAI proves its model, keys, and certs are authentic — or it refuses to start.",
            "mermaid": ATTEST,
            "speaker_notes": "The diagram slide.",
        },
        {
            "type": "content",
            "title": "How It Actually Works (the real mechanism)",
            "bullets": [
                "The boot “attestation gate” confirms three things: the weight manifest is present and its digests valid, the decision-signing TPM key is provisioned, and the per-boot certificate authority is present.",
                "Signature-BEFORE-content: the manifest’s TPM signature is verified FIRST. An attacker who can write both the manifest AND its signature still can’t craft a valid pair without the non-exportable TPM private key — so a tampered or unsigned manifest returns nothing and the boot fails closed.",
                "THEN the fingerprints: every weight file is SHA-256 hashed and compared against the now-trusted manifest; an extra file that isn’t in the manifest also fails closed.",
                "Root of trust = the TPM 2.0 chip: the manifest-signing key, the decision-signing key, and the data-key-sealing key all live in the TPM, non-exportable. Any failure ⇒ refuse to start; hard-lock after three attempts.",
            ],
            "speaker_notes": "From the seed §3 (accurate mechanism), with file grounding.",
        },
        {
            "type": "content",
            "title": "Saying It Right — Security-Material Validation, NOT Full “Measured Boot”",
            "lede": "The honest scope — and the senior-level judgment behind it.",
            "bullets": [
                "BlarAI’s attestation today validates the SECURITY MATERIAL (the model, the keys, the certs). It does NOT yet read the chip’s boot-measurement registers (PCRs) — i.e. it does not do full “measured boot” that attests the firmware/bootloader/OS chain BELOW BlarAI.",
                "That stronger control is DELIBERATELY deferred to a tracked item (#627) — not discarded.",
                "Why: match the control to the threat. Removing the air-gap adds NETWORK attack surface; security-material validation fail-closes on forged or missing trust material (the network-relevant vector). PCR measured-boot defends a PHYSICAL “evil-maid” threat — orthogonal to the network gate.",
                "And operational cost: PCR values legitimately change on every firmware/OS update; strict measured-boot fails-closed-on-boot until re-baselined (like BitLocker asking for a recovery key after an update). On a decades-of-use daily driver that deserves its own design pass, not a deadline rush.",
            ],
            "speaker_notes": "The built-vs-designed honesty (seed §4). #627 deferral is the impressive threat-matching judgment.",
        },
        {
            "type": "section",
            "title": "Why It’s a Strong Interview Topic",
            "bullets": [
                "Root of trust / hardware-backed security — keys that CANNOT be exported from a TPM, so signatures can’t be forged even with full disk-write access.",
                "Integrity verification — fingerprints (hashes) plus a signed manifest, signature-checked BEFORE the content.",
                "Fail-closed / defense-in-depth — refuse to start on any mismatch; hard-lock on repeated failure.",
                "Threat-modeling maturity — matching a control to the threat, and deliberately deferring an orthogonal control (and tracking it) rather than cargo-culting “measured boot” because it sounds strong. Knowing WHY NOT is as impressive as why.",
            ],
            "speaker_notes": "Seed §5 — the transferable interview points.",
        },
    ],
}

HOST_GUEST_DECK = {
    "title": "Host ↔ Guest — How Data Moves Securely Without Getting Lost",
    "subtitle": "A plain-language explainer of BlarAI’s secure channel between an isolated guest and the host (the 13-year-old version first, then the real mechanism).",
    "meta": "Grounded in shared/ipc/vsock.py; the host-mode-default topology; #615 (the VM-guest model). Companion to the #612 capstone deck.",
    "bar": "BlarAI Explainer — Host↔Guest Secure Data Flow",
    "slides": [
        {
            "type": "content",
            "title": "The Picture — the Sealed Vault and the One Hatch",
            "lede": "How an isolated “guest” passes data to the “host” securely, without losing any of it.",
            "bullets": [
                "In the full isolation design, the “guest” is a virtual machine with NO network card at all — so nothing on the internet can even reach it. But it still has to pass notes to the outside room (the host).",
                "It does that through one special hatch the building itself builds into the wall — a channel called vsock. The crucial part: that hatch does NOT connect to the street or the hallways (the network). It’s a private pass-through between exactly those two rooms.",
                "Nothing gets lost: every note has its page-count written on the envelope (a 4-byte number). The receiver reads that number first, then takes EXACTLY that many bytes — never one short, never two notes smeared together. Capped at 64 KB so no single note can flood the hatch.",
                "Nothing leaks: both sides must show an ID badge (a TLS certificate from a fresh authority created at every boot). EACH side checks the OTHER’s badge — that’s mutual TLS. Missing or fake badge → the hatch stays shut (fail-closed), and everything through it is in a sealed, scrambled envelope only those two can open (encryption).",
            ],
            "speaker_notes": "The spoken kid-level version, from the host-guest seed §1.",
        },
        {
            "type": "diagram",
            "title": "The vsock Hatch",
            "lede": "The guest has no network card. The only way in or out is the hypervisor’s vsock hatch — length-framed so nothing is lost, mutually-authenticated and encrypted so nothing leaks.",
            "mermaid": HOSTGUEST,
            "speaker_notes": "The diagram slide. Framing + mTLS detail is carried in the next slide's bullets to keep the diagram label short.",
        },
        {
            "type": "content",
            "title": "How It Actually Works (the real mechanism)",
            "bullets": [
                "Two production topologies, selected by one flag. Host-mode (TODAY’S DEFAULT): all services on one Windows host; the channel is loopback (127.0.0.1) + mutual TLS — which physically cannot leave the machine. Guest-mode (#615): services inside the Hyper-V VM; the channel is AF_HYPERV vsock + mutual TLS across the VM boundary.",
                "Framing: the sender writes [4-byte big-endian length][payload]; the receiver reads the 4-byte header, then reads EXACTLY N bytes (max 64 KB). That length-prefix is the “nothing lost” guarantee.",
                "Mutual TLS: both the server and client require a peer certificate (CERT_REQUIRED), verify it against the per-boot authority, set a TLS 1.2+ floor, and refuse bare/unauthenticated connections fail-closed.",
                "Hyper-V addressing: Windows vsock addresses by a GUID pair (VM-id, service-id), not the Linux (cid, port) form — the mismatch that was the #615 addressing bug, now fixed. The guest has no network card, so vsock is the ONLY host↔guest channel (a real Windows→Alpine round-trip was confirmed with 0 network cards).",
            ],
            "speaker_notes": "From the seed §3 (accurate mechanism), with file grounding.",
        },
        {
            "type": "content",
            "title": "Saying It Right — Host-Mode Is the Default; the VM-Guest Is the Designed Model (#615)",
            "lede": "The honesty guardrail — so you describe it correctly.",
            "bullets": [
                "TODAY’S DEFAULT is host-mode: the gateway and the assistant talk over an internal loopback channel that’s mutually-authenticated and encrypted — and physically cannot leave the computer.",
                "The sealed-vault VM-guest version (services inside the Hyper-V Alpine guest, talking over vsock across the hypervisor boundary) is the DESIGNED hardening, finished under #615 — built and addressable, NOT the running default. Never claim the VM isolation is “what runs by default.”",
                "Both use the SAME framing and the SAME mutual TLS — the only difference is loopback-on-one-machine vs vsock-across-the-VM-wall.",
                "A test-only dev-mode can drop mutual TLS (loopback only); it is never the production path.",
            ],
            "speaker_notes": "The built-vs-designed honesty (seed §4) — host-mode default vs VM-guest #615.",
        },
        {
            "type": "section",
            "title": "Why It’s a Strong Interview Topic",
            "bullets": [
                "Reducing attack surface — a guest with no network card cannot be reached from the internet at all.",
                "Secure inter-process communication — a private hypervisor channel instead of the network.",
                "Mutual authentication — BOTH sides prove identity (mTLS), not just the server (unlike normal HTTPS).",
                "Fail-closed design — no valid certificate ⇒ no connection; the default is “deny.”",
                "Reliable message framing — a length-prefix so messages can’t be lost, truncated, or run together.",
            ],
            "speaker_notes": "Seed §5 — the five transferable interview fundamentals.",
        },
    ],
}

# ---------------------------------------------------------------------------
# Emit both decks (outline JSON for _validate + self-contained HTML).
# ---------------------------------------------------------------------------

DECKS = [("attestation", ATTESTATION_DECK), ("host_guest", HOST_GUEST_DECK)]

for name, deck in DECKS:
    outline = {k: deck[k] for k in ("title", "subtitle", "meta", "bar", "slides")}
    (D / f"{name}_outline.json").write_text(
        json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    html_out, diagrams = render_deck(deck)
    (D / f"{name}.html").write_text(html_out, encoding="utf-8")
    print(f"wrote {name}.html ({len(deck['slides']) + 1} slides, {len(diagrams)} diagram) + {name}_outline.json")
