#!/usr/bin/env python
"""Render the disk-rooted security audit into a self-contained HTML slide deck.

Reads deck_outline.json and emits security_presentation.html. Fully local
(references a locally-saved mermaid.min.js, MIT, no cloud at view time).

Diagram embedding: each diagram's code is passed to mermaid.render() as a
JavaScript string (via a JSON map), NEVER as text inside <pre class="mermaid">.
The <pre> approach round-trips the code through the HTML parser, which re-encodes
every "-->" arrow to "--&gt;" and eats <br/> elements -> "Syntax error in text".
Passing the code straight to mermaid.render() avoids that entirely.
"""
import html
import json
import pathlib

D = pathlib.Path(__file__).resolve().parent
deck = json.loads((D / "deck_outline.json").read_text(encoding="utf-8"))

SEV = {"Critical": "#ff3b30", "High": "#ff9500", "Medium": "#ffcc00", "Low": "#34c759"}
DIAGRAMS = []  # list of [id, code]; rendered client-side via mermaid.render()


def esc(s):
    return html.escape(str(s if s is not None else ""))


def diagram(code):
    if not code or not code.strip():
        return ""
    did = "mmd%d" % len(DIAGRAMS)
    DIAGRAMS.append([did, code])
    return f'<div class="mmd" id="{did}"><span class="mmdwait">rendering diagram…</span></div>'


slides = []


def add(inner, stype="content"):
    slides.append(f'<section class="slide" data-type="{esc(stype)}">{inner}</section>')


add(
    f'<div class="titlebox"><h1>{esc(deck.get("title"))}</h1>'
    f'<p class="subtitle">{esc(deck.get("subtitle"))}</p>'
    f'<p class="meta">Disk-rooted audit &middot; 7 domains &middot; 16-agent adversarial cross-check &middot; 2026-06-03</p></div>',
    "title",
)

sysdiags = deck.get("system_diagrams", [])
attack = deck.get("top_attack_paths", [])
injected = False

for s in deck.get("slides", []):
    t = s.get("type", "content")
    title = s.get("title", "")
    body = f"<h2>{esc(title)}</h2>"
    if s.get("bullets"):
        body += "<ul>" + "".join(f"<li>{esc(b)}</li>" for b in s["bullets"]) + "</ul>"
    if s.get("mermaid"):
        body += diagram(s["mermaid"])
    add(body, "section" if t == "section" else t)

    if t == "diagram" and not injected and "rchitect" in title:
        injected = True
        for sd in sysdiags:
            add(f'<h2>{esc(sd.get("title"))}</h2>{diagram(sd.get("mermaid"))}', "diagram")

    if t == "diagram" and "ttack" in title and attack:
        rows = ""
        for ap in attack:
            c = SEV.get(ap.get("severity"), "#888")
            net = '<span class="net">NETWORK-FACING</span>' if ap.get("network_facing") else ""
            rows += (
                f'<div class="apath"><span class="sev" style="background:{c}">{esc(ap.get("severity"))}</span>{net}'
                f'<b>{esc(ap.get("name"))}</b><div class="apd">{esc(ap.get("description"))}</div>'
                f'<div class="apby">Enabled by: {esc(ap.get("enabled_by"))}</div></div>'
            )
        add(f"<h2>Top Attack Paths &mdash; detail</h2><div class=\"apaths\">{rows}</div>", "content")

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
.slide{display:none;flex-direction:column;justify-content:center;height:100vh;width:100vw;padding:5vh 7vw 9vh;overflow-y:auto}
.slide.active{display:flex}
.slide[data-type=section],.slide[data-type=title]{align-items:center;text-align:center}
.titlebox h1{font-size:2.6rem;max-width:20ch;line-height:1.15;margin:.1em auto}
.subtitle{font-size:1.3rem;color:var(--ac);max-width:62ch;margin:.4em auto}
.meta{color:var(--mut);font-size:.95rem}
h2{font-size:1.85rem;color:var(--ac);margin:0 0 .55em;border-bottom:2px solid var(--bd);padding-bottom:.3em}
ul{font-size:1.22rem;line-height:1.6;max-width:82ch}li{margin:.35em 0}
.slide[data-type=section] h2{font-size:2.4rem;border:0;color:var(--fg)}
.mmd{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:1.1em;margin-top:.8em;text-align:center;max-width:94ch;overflow-x:auto}
.mmd svg{max-width:100%;height:auto}
.mmdwait{color:var(--mut)}.mmderr{color:#ff6b6b;text-align:left;white-space:pre-wrap;font-family:monospace}
.apaths{display:grid;gap:.55em;max-width:94ch}
.apath{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:.65em .95em}
.sev{color:#000;font-weight:700;font-size:.78rem;padding:.15em .6em;border-radius:4px;margin-right:.55em}
.net{background:#1f6feb;color:#fff;font-size:.68rem;padding:.12em .5em;border-radius:4px;margin-right:.55em;font-weight:700}
.apd{margin-top:.3em;font-size:1.04rem}.apby{color:var(--mut);font-size:.88rem;margin-top:.2em}
#bar{position:fixed;bottom:0;left:0;right:0;display:flex;justify-content:space-between;align-items:center;padding:.5em 1.2em;background:#010409cc;border-top:1px solid var(--bd);font-size:.85rem;color:var(--mut)}
#bar b{color:var(--ac)}
kbd{background:var(--card);border:1px solid var(--bd);border-radius:4px;padding:.1em .4em}
</style></head><body>
<div id="deck">__SLIDES__</div>
<div id="bar"><span>BlarAI Security Posture &mdash; 2026-06-03</span><span><kbd>&larr;</kbd> <kbd>&rarr;</kbd> navigate &middot; <b><span id="cur">1</span></b>/<span id="tot">1</span></span></div>
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

out = (
    TEMPLATE.replace("__TITLE__", esc(deck.get("title")))
    .replace("__SLIDES__", "\n".join(slides))
    .replace("__MMD__", json.dumps(DIAGRAMS))
)
(D / "security_presentation.html").write_text(out, encoding="utf-8")
print("wrote security_presentation.html with", len(slides), "slides,", len(DIAGRAMS), "diagrams (render-API embedding)")
