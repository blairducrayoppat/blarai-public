#!/usr/bin/env python
"""Render the #612 capstone security presentation into a self-contained HTML deck.

The "after / verified posture" closing bookend to docs/security/audit_2026-06-03/.
Reads deck_outline.json and emits capstone_presentation.html. Fully local
(references a locally-saved mermaid.min.js, MIT, no cloud at view time).

Diagram embedding (inherited from the audit deck's build_deck.py, and load-bearing):
each diagram's code is passed to mermaid.render() as a JavaScript string via a JSON
map (const MMD), NEVER as text inside <pre class="mermaid">. The <pre> approach
round-trips the code through the HTML parser, which re-encodes every "-->" arrow to
"--&gt;" and eats <br/> elements -> "Syntax error in text". Passing the code straight
to mermaid.render() avoids that entirely. Diagrams are authored conservatively
(every node/edge label quoted, real newlines, balanced subgraph/end + brackets) so
the audit deck's fix_diagrams.py post-pass is not needed.

Schema (deck_outline.json):
  title, subtitle, meta            -- strings (title slide)
  system_diagrams: [{title, mermaid}]   -- injected after the architecture slide
  slides: [ { title, type, bullets[], mermaid, speaker_notes, ...payload } ]
    type "section"|"content"|"diagram"|"table"  -- standard bullet/diagram slide
    type "scorecard"  -> reads slide["scorecard"]   (before/after status summary)
    type "matrix"     -> reads slide["matrix"]       (per-domain before->after table)
    type "cards"      -> reads slide["cards"]         (per-issue reconciliation cards)
    type "attack"     -> reads slide["attack"]        (attack-paths then->now cards)
    type "residual"   -> reads slide["residual"]      (the air-gap residual register)
"""
import html
import json
import pathlib

D = pathlib.Path(__file__).resolve().parent
deck = json.loads((D / "deck_outline.json").read_text(encoding="utf-8"))

# Severity palette (matches the audit deck).
SEV = {"Critical": "#ff3b30", "High": "#ff9500", "Medium": "#ffcc00", "Low": "#34c759"}
# Reconciliation-status palette.
STAT = {
    "FIXED": "#2ea043",
    "MITIGATED": "#1f6feb",
    "BUILT-DORMANT": "#d29922",
    "ACCEPTED-RESIDUAL": "#8957e5",
    "STILL-OPEN": "#da3633",
    "CLOSED": "#2ea043",
}
# Built-vs-verified honesty grades (text badge).
GRADE = {
    "VERIFIED-LIVE": "#2ea043",
    "TESTED": "#1f6feb",
    "BUILT-DORMANT": "#d29922",
    "DESIGNED-DEFERRED": "#8957e5",
}
DIAGRAMS = []  # list of [id, code]; rendered client-side via mermaid.render()


def esc(s):
    return html.escape(str(s if s is not None else ""))


def diagram(code):
    if not code or not code.strip():
        return ""
    did = "mmd%d" % len(DIAGRAMS)
    DIAGRAMS.append([did, code])
    return f'<div class="mmd" id="{did}"><span class="mmdwait">rendering diagram…</span></div>'


def chip(value, palette, cls="sev"):
    c = palette.get(value, "#8b949e")
    return f'<span class="{cls}" style="background:{c}">{esc(value)}</span>'


def grade_badge(value):
    if not value:
        return ""
    c = GRADE.get(value, "#8b949e")
    return f'<span class="grade" style="border-color:{c};color:{c}">{esc(value)}</span>'


slides = []


def add(inner, stype="content"):
    slides.append(f'<section class="slide" data-type="{esc(stype)}">{inner}</section>')


def render_scorecard(sc):
    """Before->after status summary grid + the headline counts."""
    out = ""
    if sc.get("intro"):
        out += f'<p class="lede">{esc(sc["intro"])}</p>'
    # Severity before-counts row.
    sev = sc.get("before_severity", {})
    if sev:
        cells = "".join(
            f'<div class="scell"><div class="snum">{esc(sev.get(k, 0))}</div>'
            f'<div class="slabel">{chip(k, SEV)}</div></div>'
            for k in ("Critical", "High", "Medium", "Low")
        )
        out += f'<div class="scard"><div class="scaption">The 2026-06-03 audit raised</div><div class="sgrid">{cells}</div></div>'
    # Status after-counts row.
    st = sc.get("after_status", {})
    if st:
        order = ["FIXED", "MITIGATED", "BUILT-DORMANT", "ACCEPTED-RESIDUAL", "STILL-OPEN"]
        cells = "".join(
            f'<div class="scell"><div class="snum">{esc(st.get(k, 0))}</div>'
            f'<div class="slabel">{chip(k, STAT)}</div></div>'
            for k in order if k in st
        )
        out += f'<div class="scard"><div class="scaption">Where every finding stands today</div><div class="sgrid">{cells}</div></div>'
    for note in sc.get("notes", []):
        out += f'<p class="snote">{esc(note)}</p>'
    return out


def render_matrix(rows):
    """Per-domain before->after table."""
    head = (
        "<tr><th>Domain</th><th>Audit raised</th>"
        "<th>Fixed</th><th>Mitigated</th><th>Dormant</th><th>Residual</th><th>Open</th>"
        "<th>Headline of the change</th></tr>"
    )
    body = ""
    for r in rows:
        b = r.get("before", {})
        bsev = " ".join(
            f'{esc(b[k])}{k[0]}' for k in ("Critical", "High", "Medium", "Low") if b.get(k)
        )
        body += (
            "<tr>"
            f'<td class="dname">{esc(r.get("domain"))}</td>'
            f'<td class="dcount">{bsev}</td>'
            f'<td>{esc(r.get("fixed", ""))}</td>'
            f'<td>{esc(r.get("mitigated", ""))}</td>'
            f'<td>{esc(r.get("dormant", ""))}</td>'
            f'<td>{esc(r.get("residual", ""))}</td>'
            f'<td>{esc(r.get("open", ""))}</td>'
            f'<td class="dhead">{esc(r.get("headline", ""))}</td>'
            "</tr>"
        )
    return f'<div class="mtxwrap"><table class="mtx">{head}{body}</table></div>'


def render_cards(cards):
    out = '<div class="cards">'
    for c in cards:
        was = f'<div class="cwas"><b>What it was:</b> {esc(c.get("was"))}</div>' if c.get("was") else ""
        body = c.get("did") or c.get("gap") or ""
        body_label = "What we did" if c.get("did") else "The gap"
        bodyhtml = f'<div class="cdid"><b>{body_label}:</b> {esc(body)}</div>' if body else ""
        ev = f'<div class="cev">Evidence: {esc(c.get("evidence"))}</div>' if c.get("evidence") else ""
        tk = f'<span class="cticket">{esc(c.get("ticket"))}</span>' if c.get("ticket") else ""
        out += (
            '<div class="card">'
            f'<div class="chead">{chip(c.get("severity"), SEV)}{chip(c.get("status"), STAT)}'
            f'{grade_badge(c.get("grade"))}{tk}<b class="ctitle">{esc(c.get("title"))}</b></div>'
            f'{was}{bodyhtml}{ev}'
            "</div>"
        )
    out += "</div>"
    return out


def render_attack(paths):
    out = '<div class="cards">'
    for p in paths:
        net = '<span class="net">NETWORK-FACING</span>' if p.get("network_facing") else '<span class="local">LOCAL-ONLY</span>'
        note = f'<div class="cdid">{esc(p.get("note"))}</div>' if p.get("note") else ""
        out += (
            '<div class="card">'
            f'<div class="chead">{chip(p.get("was_severity"), SEV)}{chip(p.get("status"), STAT)}'
            f'{net}<b class="ctitle">{esc(p.get("name"))}</b></div>'
            f'{note}'
            "</div>"
        )
    out += "</div>"
    return out


def render_residual(items):
    out = '<div class="cards">'
    for it in items:
        tk = f'<span class="cticket">{esc(it.get("ticket"))}</span>' if it.get("ticket") else ""
        why = f'<div class="cwhy"><b>Why acceptable for the gate:</b> {esc(it.get("why_acceptable"))}</div>' if it.get("why_acceptable") else ""
        what = f'<div class="cdid"><b>What can still go wrong:</b> {esc(it.get("risk"))}</div>' if it.get("risk") else ""
        out += (
            '<div class="card resid">'
            f'<div class="chead">{chip(it.get("status"), STAT)}{grade_badge(it.get("grade"))}{tk}'
            f'<b class="ctitle">{esc(it.get("item"))}</b></div>'
            f'{what}{why}'
            "</div>"
        )
    out += "</div>"
    return out


sysdiags = deck.get("system_diagrams", [])
injected = False

for s in deck.get("slides", []):
    t = s.get("type", "content")
    title = s.get("title", "")
    body = f"<h2>{esc(title)}</h2>"
    if s.get("lede"):
        body += f'<p class="lede">{esc(s["lede"])}</p>'
    if s.get("bullets"):
        body += "<ul>" + "".join(f"<li>{esc(b)}</li>" for b in s["bullets"]) + "</ul>"
    if t == "scorecard" and s.get("scorecard"):
        body += render_scorecard(s["scorecard"])
    if t == "matrix" and s.get("matrix"):
        body += render_matrix(s["matrix"])
    if t == "cards" and s.get("cards"):
        body += render_cards(s["cards"])
    if t == "attack" and s.get("attack"):
        body += render_attack(s["attack"])
    if t == "residual" and s.get("residual"):
        body += render_residual(s["residual"])
    if s.get("mermaid"):
        body += diagram(s["mermaid"])
    norm_type = t if t in ("section", "diagram") else ("section" if t == "section" else t)
    add(body, "section" if t == "section" else t)

    # Inject the hardened-state system diagrams right after the architecture slide.
    if t == "diagram" and not injected and "rchitect" in title:
        injected = True
        for sd in sysdiags:
            add(f'<h2>{esc(sd.get("title"))}</h2>{diagram(sd.get("mermaid"))}', "diagram")

if not injected:
    for sd in sysdiags:
        add(f'<h2>{esc(sd.get("title"))}</h2>{diagram(sd.get("mermaid"))}', "diagram")

TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script src="mermaid.min.js"></script>
<style>
:root{--bg:#0d1117;--fg:#e6edf3;--ac:#58a6ff;--mut:#8b949e;--card:#161b22;--bd:#30363d}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif}
#deck{height:100vh;width:100vw;overflow:hidden;position:relative}
.slide{display:none;flex-direction:column;justify-content:center;height:100vh;width:100vw;padding:4.5vh 6vw 8vh;overflow-y:auto}
.slide.active{display:flex}
.slide[data-type=section],.slide[data-type=title]{align-items:center;text-align:center}
.titlebox h1{font-size:2.5rem;max-width:24ch;line-height:1.15;margin:.1em auto}
.subtitle{font-size:1.25rem;color:var(--ac);max-width:66ch;margin:.4em auto}
.meta{color:var(--mut);font-size:.95rem;max-width:70ch;margin:.6em auto}
h2{font-size:1.7rem;color:var(--ac);margin:0 0 .5em;border-bottom:2px solid var(--bd);padding-bottom:.3em}
ul{font-size:1.1rem;line-height:1.5;max-width:88ch}li{margin:.28em 0}
.lede{font-size:1.18rem;color:var(--fg);max-width:88ch;margin:.2em 0 .7em;line-height:1.5}
.slide[data-type=section] h2{font-size:2.2rem;border:0;color:var(--fg)}
.mmd{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:1.1em;margin-top:.7em;text-align:center;max-width:96ch;overflow-x:auto}
.mmd svg{max-width:100%;height:auto}
.mmdwait{color:var(--mut)}.mmderr{color:#ff6b6b;text-align:left;white-space:pre-wrap;font-family:monospace}
/* status / severity / grade chips */
.sev,.stat{color:#000;font-weight:700;font-size:.74rem;padding:.14em .55em;border-radius:4px;margin-right:.45em;white-space:nowrap}
.grade{font-size:.66rem;font-weight:700;padding:.1em .45em;border-radius:4px;border:1px solid;margin-right:.45em;white-space:nowrap}
.net{background:#1f6feb;color:#fff;font-size:.66rem;padding:.12em .5em;border-radius:4px;margin-right:.45em;font-weight:700}
.local{background:#30363d;color:#adbac7;font-size:.66rem;padding:.12em .5em;border-radius:4px;margin-right:.45em;font-weight:700}
/* scorecard */
.scard{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:.8em 1.1em;margin:.6em 0;max-width:92ch}
.scaption{color:var(--mut);font-size:.95rem;margin-bottom:.5em}
.sgrid{display:flex;gap:1.4em;flex-wrap:wrap;align-items:flex-end}
.scell{text-align:center}.snum{font-size:1.9rem;font-weight:800}.slabel{margin-top:.2em}
.snote{color:var(--mut);font-size:.98rem;max-width:90ch;margin:.35em 0}
/* matrix table */
.mtxwrap{max-width:122ch;overflow-x:auto}
.mtx{border-collapse:collapse;font-size:.88rem;width:100%}
.mtx th,.mtx td{border:1px solid var(--bd);padding:.3em .5em;text-align:center;vertical-align:top}
.mtx th{background:#161b22;color:var(--ac);font-size:.9rem}
.mtx .dname{text-align:left;font-weight:600;white-space:nowrap}
.mtx .dcount{color:var(--mut);white-space:nowrap}
.mtx .dhead{text-align:left;color:var(--fg);font-size:.82rem;max-width:30ch}
/* cards */
.cards{display:grid;gap:.45em;max-width:96ch}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:.45em .8em;border-left:4px solid var(--bd)}
.card.resid{border-left-color:#8957e5}
.chead{display:flex;flex-wrap:wrap;align-items:center;gap:.15em}
.ctitle{font-size:.97rem}
.cwas,.cdid,.cev,.cwhy{margin-top:.18em;font-size:.89rem;line-height:1.3}
.cev{color:var(--mut);font-size:.84rem;font-family:ui-monospace,Consolas,monospace}
.cticket{background:#30363d;color:#adbac7;font-size:.7rem;padding:.1em .5em;border-radius:4px;margin-right:.45em;font-weight:700}
#bar{position:fixed;bottom:0;left:0;right:0;display:flex;justify-content:space-between;align-items:center;padding:.5em 1.2em;background:#010409cc;border-top:1px solid var(--bd);font-size:.85rem;color:var(--mut)}
#bar b{color:var(--ac)}
kbd{background:var(--card);border:1px solid var(--bd);border-radius:4px;padding:.1em .4em}
</style></head><body>
<div id="deck">__SLIDES__</div>
<div id="bar"><span>BlarAI Security Capstone &mdash; the verified posture &middot; 2026-06</span><span><kbd>&larr;</kbd> <kbd>&rarr;</kbd> navigate &middot; <b><span id="cur">1</span></b>/<span id="tot">1</span></span></div>
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

# Title slide is always first.
title_slide = (
    f'<div class="titlebox"><h1>{esc(deck.get("title"))}</h1>'
    f'<p class="subtitle">{esc(deck.get("subtitle"))}</p>'
    f'<p class="meta">{esc(deck.get("meta"))}</p></div>'
)
slides.insert(0, f'<section class="slide" data-type="title">{title_slide}</section>')

out = (
    TEMPLATE.replace("__TITLE__", esc(deck.get("title")))
    .replace("__SLIDES__", "\n".join(slides))
    .replace("__MMD__", json.dumps(DIAGRAMS))
)
(D / "capstone_presentation.html").write_text(out, encoding="utf-8")
print("wrote capstone_presentation.html with", len(slides), "slides,", len(DIAGRAMS), "diagrams (render-API embedding)")
