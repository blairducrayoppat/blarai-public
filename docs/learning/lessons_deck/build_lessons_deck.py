#!/usr/bin/env python
"""Render the lessons teaching deck into a self-contained HTML file (v2).

Reads acts/act1.json .. acts/act8.json (validated by validate_acts.py) plus
core_path.json and emits lessons_deck.html. Fully local (vendored
mermaid.min.js, MIT — no cloud at view time). Diagram-embedding pattern
inherited from docs/security/capstone_2026-06/build_deck.py: diagram code is
passed to mermaid.render() via a JSON map (const MMD), never inside
<pre class="mermaid">, because the HTML parser re-encodes "-->" arrows and
eats <br/> elements.

Teaching structure (one unit = one lesson = a 3- or 4-slide cluster):
  slide A  "The failure"    — the story + stats + evidence + a Socratic question
  slide M  "The mechanism"  — only when the unit carries a diagram: the failure's
                              moving parts drawn, plus the stat callouts
  slide B  "The lesson"     — distilled principle + what to understand to grow
  slide C  "The AIGP connection" — domain/framework chips + takeaway + studied-toggle

v2 additions:
  - per-act accent colors (intros, header strip, index, top rail)
  - per-domain colors on AIGP chips (Domains I–IV)
  - per-unit mermaid diagrams ("diagram") and big-number stats ("stat")
  - the CORE PATH: core_path.json names the ~30-lesson default study track;
    the deck opens in core mode (navigation skips non-core units; press c or
    use the bar button for the full deck)
  - test hooks: ?audit=1 runs an in-page geometry/paint/diagram audit over
    every slide and writes a JSON report into <pre id="auditout"> (and the
    document title); ?selftest=1 exercises nav/index/studied/mode/resume the
    same way. Both use a separate localStorage key so tests never pollute
    real study progress. Driven headless by run_checks.py.

Study features (all client-side, localStorage, no network):
  - clickable journey index of all units; studied units get a check
  - "Mark studied" toggle per unit; bar shows core + total studied counts
  - resume: reopening the deck returns to the last slide viewed
  - keys: arrows/space/PgUp/PgDn slides; n/p units; c core/full; i index; Home title
"""
import html
import json
import pathlib

D = pathlib.Path(__file__).resolve().parent
GENERATED = "2026-06-11"

acts = []
for n in range(1, 9):
    acts.append(json.loads((D / "acts" / f"act{n}.json").read_text(encoding="utf-8")))

core_cfg = json.loads((D / "core_path.json").read_text(encoding="utf-8"))
CORE = set(core_cfg["core"])

ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}
ACT_COLORS = {1: "#79c0ff", 2: "#39c5cf", 3: "#d29922", 4: "#d2a8ff",
              5: "#f85149", 6: "#56d364", 7: "#ff9bce", 8: "#ffa657"}
PROLOGUE_COLOR = "#e6edf3"
DOMAIN_COLORS = {"Domain I": "#d2a8ff", "Domain II": "#79c0ff",
                 "Domain III": "#56d364", "Domain IV": "#ffa657"}

# ---------------------------------------------------------------------------
# Deck-level diagrams. The study-loop strip is pure HTML (a mermaid LR chain
# renders as an illegible 45px ribbon once scaled to the card — caught in the
# 2026-06-10 visual pass); only the domains map is mermaid.
# ---------------------------------------------------------------------------
METHOD_STRIP = (
    '<div class="methodstrip">'
    '<span class="ms" style="border-color:var(--fail);color:var(--fail)">1 &middot; The failure</span><span class="msarrow">&#8594;</span>'
    '<span class="ms" style="border-color:#39c5cf;color:#39c5cf">the mechanism, drawn</span><span class="msarrow">&#8594;</span>'
    '<span class="ms" style="border-color:var(--mut);color:var(--mut)">stop &middot; think</span><span class="msarrow">&#8594;</span>'
    '<span class="ms" style="border-color:var(--lesson);color:var(--lesson)">2 &middot; The lesson</span><span class="msarrow">&#8594;</span>'
    '<span class="ms" style="border-color:var(--grow);color:var(--grow)">3 &middot; Growing from it</span><span class="msarrow">&#8594;</span>'
    '<span class="ms" style="border-color:var(--aigp);color:var(--aigp)">4 &middot; The AIGP connection</span><span class="msarrow">&#8594;</span>'
    '<span class="ms" style="border-color:var(--grow);color:var(--grow)">mark studied</span>'
    "</div>"
)

DOMAINS = """flowchart TD
  BOK["IAPP AIGP Body of Knowledge v2.1<br/>(effective 2026-02-02)"] --> D1["Domain I<br/>Foundations of AI Governance"]
  BOK --> D2["Domain II<br/>Laws, Standards and Frameworks"]
  BOK --> D3["Domain III<br/>Govern AI Development"]
  BOK --> D4["Domain IV<br/>Govern AI Deployment and Use"]
  D2 --- FW["NIST AI RMF 1.0 (GOVERN, MAP,<br/>MEASURE, MANAGE + TEVV)<br/>ISO/IEC 42001 and 42005"]
  D2 --- LAW["EU AI Act (risk tiers)<br/>OECD AI Principles"]
"""

DIAGRAMS = []


def esc(s):
    return html.escape(str(s if s is not None else ""))


def diagram(code):
    did = "mmd%d" % len(DIAGRAMS)
    DIAGRAMS.append([did, code])
    return f'<div class="mmd" id="{did}"><span class="mmdwait">rendering diagram…</span></div>'


def fchips(values):
    return "".join(f'<span class="fchip">{esc(v)}</span>' for v in values)


def dchips(values):
    out = []
    for v in values:
        col = next((c for k, c in DOMAIN_COLORS.items() if str(v).startswith(k)), "#c5b3f0")
        out.append(f'<span class="dchip" style="border-color:{col};color:{col}">{esc(v)}</span>')
    return "".join(out)


def stat_row(stats):
    out = ['<div class="statrow">']
    for s in stats:
        lab = f'<span class="slabel">{esc(s.get("label", ""))}</span>'
        if "value" in s:
            row = f'<span class="svrow"><span class="sv">{esc(s["value"])}</span></span>'
        else:
            row = (f'<span class="svrow"><span class="sv svbefore">{esc(s.get("before", ""))}</span>'
                   f'<span class="sarrow">&#8594;</span><span class="sv">{esc(s.get("after", ""))}</span></span>')
        out.append(f'<span class="stat">{row}{lab}</span>')
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Assemble the unit list in render order (prologue first, then acts 1..8).
# ---------------------------------------------------------------------------
units = []  # (unit_dict, act_dict, unit_id, header_label)
prologue = None
for a in acts:
    for u in a["lessons"]:
        if u.get("prologue"):
            prologue = (u, a)

frag_counter = 0
if prologue is None:
    raise SystemExit("prologue unit (#1) not found")
units.append((prologue[0], prologue[1], "L1", "Prologue"))
for a in acts:
    label = f"Act {ROMAN[a['act']]}"
    for u in a["lessons"]:
        if u.get("prologue"):
            continue  # rendered as the deck prologue
        if u.get("number") is not None:
            uid = f"L{u['number']}"
        else:
            frag_counter += 1
            uid = f"F{frag_counter:02d}"
        units.append((u, a, uid, label))

N_UNITS = len(units)
N_DIAG_UNITS = sum(1 for u, _, _, _ in units if u.get("diagram"))
TOTAL_NUMBERED = sum(1 for u, _, _, _ in units if u.get("number") is not None)
N_FRAG = N_UNITS - TOTAL_NUMBERED

missing_core = CORE - {uid for _, _, uid, _ in units}
if missing_core:
    raise SystemExit(f"core_path.json names unknown units: {sorted(missing_core)}")

# ---------------------------------------------------------------------------
# Slides.
# ---------------------------------------------------------------------------
slides = []            # html strings
unit_first_slide = {}  # uid -> slide index (before the title-slide shift)


def add(inner, stype="content", unit=None, uidx=None, act="", core=False):
    du = f' data-unit="{esc(unit)}" data-unitidx="{uidx}" data-core="{1 if core else 0}"' if unit else ""
    slides.append(f'<section class="slide" data-type="{esc(stype)}" data-act="{esc(act)}"{du}>{inner}</section>')


def act_color(a):
    return ACT_COLORS.get(a["act"], PROLOGUE_COLOR)


def unit_header(uid, label, u, uidx, beat, a):
    if u.get("number") is not None:
        what = "Prologue — Lesson 1" if u.get("prologue") else f"Lesson {u['number']}"
    else:
        what = "June 2026 — not yet folded"
    beat_list = [("A", "failure")]
    if u.get("diagram"):
        beat_list.append(("M", "mechanism"))
    beat_list += [("B", "lesson + growth"), ("C", "AIGP")]
    beats = "".join(
        f'<span class="bcrumb{" on" if b == beat else ""}">{t}</span>' for b, t in beat_list
    )
    col = PROLOGUE_COLOR if u.get("prologue") else act_color(a)
    core_b = '<span class="corebadge">core path</span>' if uid in CORE else ""
    return (
        f'<div class="uhead"><span class="uact" style="color:{col}">{esc(label)}</span>'
        f'<span class="uwhat">{esc(what)}</span>{core_b}'
        f'<span class="ucount">unit {uidx + 1} / {N_UNITS}</span>'
        f'<span class="ubeats">{beats}</span></div>'
    )


def render_unit(u, a, uid, label, uidx):
    unit_first_slide[uid] = len(slides)
    is_core = uid in CORE
    title = f'<h2 class="utitle">{esc(u["title"])}</h2>'
    has_diag = bool(u.get("diagram"))
    stats = u.get("stat") or []
    # Slide A — the failure (stats shown here when there is no mechanism slide).
    ev = " · ".join(esc(e) for e in u.get("evidence", []))
    add(
        unit_header(uid, label, u, uidx, "A", a) + title
        + '<div class="beat beat-fail"><span class="btag tfail">The failure</span>'
        + f'<p class="prose">{esc(u["failure"])}</p>'
        + (stat_row(stats) if (stats and not has_diag) else "")
        + f'<div class="evidence">Evidence: {ev}</div></div>'
        + '<div class="thinkbox"><div class="tb-cap">Before you turn the page</div>'
        + f'<p class="tb-q">{esc(u["growth_question"])}</p></div>',
        "lesson-fail", uid, uidx, label, is_core,
    )
    # Slide M — the mechanism (only when a diagram exists).
    if has_diag:
        add(
            unit_header(uid, label, u, uidx, "M", a) + title
            + '<div class="mechwrap"><span class="btag tmech">The mechanism, drawn</span>'
            + diagram(u["diagram"])
            + (stat_row(stats) if stats else "")
            + "</div>",
            "lesson-mech", uid, uidx, label, is_core,
        )
    # Slide B — the lesson + growing from it.
    add(
        unit_header(uid, label, u, uidx, "B", a) + title
        + '<div class="beat beat-lesson"><span class="btag tlesson">The lesson</span>'
        + f'<p class="prose lprose">{esc(u["lesson"])}</p></div>'
        + '<div class="beat beat-grow"><span class="btag tgrow">Growing from it</span>'
        + f'<p class="prose">{esc(u["growth"])}</p></div>',
        "lesson-learn", uid, uidx, label, is_core,
    )
    # Slide C — the AIGP connection.
    add(
        unit_header(uid, label, u, uidx, "C", a) + title
        + '<div class="beat beat-aigp"><span class="btag taigp">The AIGP connection</span>'
        + f'<div class="chiprow">{dchips(u.get("aigp_domains", []))}{fchips(u.get("aigp_frameworks", []))}</div>'
        + f'<p class="prose">{esc(u["aigp_text"])}</p>'
        + f'<div class="takeaway"><span class="tk-cap">AIGP takeaway</span> {esc(u["aigp_takeaway"])}</div></div>'
        + f'<button class="studied-btn" onclick="toggleStudied(\'{uid}\')">Mark studied</button>',
        "lesson-aigp", uid, uidx, label, is_core,
    )


# --- 1: how to use ----------------------------------------------------------
add(
    "<h2>How to use this deck</h2>"
    '<p class="lede">One lesson at a time. Each lesson is a small study unit: sit with the failure first; where the unit carries a diagram, see the mechanism drawn; answer the question in your own words before turning the page; check yourself against the distilled lesson — and finish by naming the governance principle it exemplifies, in the AIGP\'s vocabulary.</p>'
    + METHOD_STRIP
    + "<ul>"
    f"<li><b>The core path</b> — the deck opens on a curated {len(CORE)}-lesson track (the most governance-loaded lessons, marked <span class=\"corebadge\">core path</span>). Arrows and <kbd>n</kbd>/<kbd>p</kbd> skip everything else. Press <kbd>c</kbd> (or the bar button) any time for the full {N_UNITS}-unit deck.</li>"
    "<li><kbd>&larr;</kbd> <kbd>&rarr;</kbd> move a slide; <kbd>n</kbd> / <kbd>p</kbd> jump a whole lesson; <kbd>i</kbd> opens the index; <kbd>Home</kbd> returns here.</li>"
    "<li><b>Mark studied</b> on a lesson's last slide tracks progress (stored locally in this browser, nowhere else). The deck reopens where you left off.</li>"
    "<li>Work with the tutor session or alone — the canonical cross-session record is <code>learning_log.md</code>, kept by the presenter.</li>"
    "</ul>",
    "content", act="Guide",
)

# --- 2: the AIGP frame ------------------------------------------------------
add(
    "<h2>The AIGP frame these lessons are studied through</h2>"
    '<p class="lede">AIGP — Artificial Intelligence Governance Professional, the IAPP certification — tests whether you can govern an AI system across its life: set expectations, apply laws and frameworks, govern development, govern deployment. Every lesson in this deck ends by naming the governance idea its failure exemplifies, so studying the project is studying the syllabus.</p>'
    + diagram(DOMAINS)
    + '<p class="snote">Framework names verified against the sources in <code>aigp_vocabulary.md</code>. Frameworks are voluntary unless law applies — lessons "exemplify" them; EU AI Act references are concept-level. Honest scope note: these lessons map mostly to Domains I, III and IV — Domain II (laws as applied) needs the official Body of Knowledge materials, which this deck complements, not replaces.</p>',
    "content", act="Guide",
)

# --- 3: index (filled by JS so studied-state stays live) ---------------------
add('<h2>The journey — every lesson, one sitting at a time</h2><div id="indexbox"></div>', "index", act="Index")

# --- 4: prologue + acts ------------------------------------------------------
uidx = 0
u, a, uid, label = units[0]
add(
    f'<div class="actcard" style="border-left-color:{PROLOGUE_COLOR}"><div class="actkicker" style="color:{PROLOGUE_COLOR}">Prologue — where the whole journal begins</div>'
    f'<h2>{esc(u["title"])}</h2>'
    f'<p class="lede">{esc(a["subtitle"])}</p>'
    '<p class="snote">The founding failure: months of automated "work" that produced documents about work. Every later lesson stands on what this one exposed.</p></div>',
    "section", act="Prologue",
)
render_unit(u, a, uid, label, uidx)
uidx += 1

for a in acts:
    body_units = [t for t in units if t[1] is a and not t[0].get("prologue")]
    if not body_units:
        continue
    nums = [t[0].get("number") for t in body_units]
    span = (
        f"lessons {min(x for x in nums if x is not None)}–{max(x for x in nums if x is not None)} (thematic, not contiguous)"
        if any(x is not None for x in nums) else f"{len(body_units)} June 2026 lessons, numbers assigned at fold-in"
    )
    n_core = sum(1 for t in body_units if (f"L{t[0]['number']}" if t[0].get("number") is not None else "") in CORE
                 or t[2] in CORE)
    col = act_color(a)
    add(
        f'<div class="actcard" style="border-left-color:{col}"><div class="actkicker" style="color:{col}">Act {ROMAN[a["act"]]} of 8 &middot; {len(body_units)} lessons &middot; {esc(span)}{f" &middot; {n_core} on the core path" if n_core else ""}</div>'
        f'<h2>{esc(a["title"])}</h2><p class="lede">{esc(a["subtitle"])}</p>'
        f'<div class="chiprow">{dchips(a.get("aigp_domains", []))}</div>'
        f'<p class="prose aintro">{esc(a["aigp_intro"])}</p></div>',
        "section", act=f"Act {ROMAN[a['act']]}",
    )
    for u, act_d, uid, label in body_units:
        render_unit(u, act_d, uid, label, uidx)
        uidx += 1

# --- closing slide -----------------------------------------------------------
add(
    "<h2>The deck grows with the journal</h2>"
    '<p class="lede">These lessons are the distilled cost of real failures — kept honest on purpose, because a sanitised lesson teaches nothing. When new fragments fold into the numbered list and new entries land, regenerate and re-test with one command: <code>python run_checks.py</code> (validate &#8594; build &#8594; diagram parse &#8594; headless render audit).</p>'
    f'<p class="snote">Source: LESSONS.md ({TOTAL_NUMBERED} numbered lessons; moved out of BUILD_JOURNAL.md 2026-07-03) + docs/journal_fragments/ ({N_FRAG} not-yet-folded June 2026 units). Generated {GENERATED}. Study progress lives only in this browser\'s localStorage.</p>',
    "section", act="End",
)

# ---------------------------------------------------------------------------
# Index data for JS.
# ---------------------------------------------------------------------------
def idx_item(u, uid):
    return {
        "uid": uid,
        "n": str(u["number"]) if u.get("number") is not None else "Jun",
        "t": u["title"],
        "s": unit_first_slide[uid],
        "c": 1 if uid in CORE else 0,
    }


index_groups = [{
    "name": "Prologue",
    "color": PROLOGUE_COLOR,
    "items": [idx_item(units[0][0], "L1")],
}]
for a in acts:
    items = []
    for u, act_d, uid, label in units:
        if act_d is a and not u.get("prologue"):
            items.append(idx_item(u, uid))
    index_groups.append({"name": f"Act {ROMAN[a['act']]} — {a['title']}", "color": act_color(a), "items": items})

RAILDATA = [{"name": g["name"].split(" — ")[0], "color": g["color"], "n": len(g["items"])} for g in index_groups]

TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script src="mermaid.min.js"></script>
<style>
:root{--bg:#0d1117;--fg:#e6edf3;--ac:#58a6ff;--mut:#8b949e;--card:#161b22;--bd:#30363d;
--fail:#ff9500;--lesson:#58a6ff;--grow:#2ea043;--aigp:#8957e5;--mech:#39c5cf}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif}
#deck{height:100vh;width:100vw;overflow:hidden;position:relative}
.slide{display:none;flex-direction:column;justify-content:flex-start;height:100vh;width:100vw;padding:4.4vh 6vw 9vh;overflow-y:auto}
.slide.active{display:flex}
.slide>*{flex-shrink:0}  /* a fixed-height column flexbox CRUSHES children (default flex-shrink:1) — the diagram card was compressed under its own svg; slides scroll instead */
.slide[data-type=section],.slide[data-type=title]{align-items:center;text-align:center;justify-content:center}
.titlebox h1{font-size:2.4rem;max-width:26ch;line-height:1.15;margin:.1em auto}
.subtitle{font-size:1.2rem;color:var(--ac);max-width:70ch;margin:.4em auto}
.meta{color:var(--mut);font-size:.95rem;max-width:74ch;margin:.6em auto}
.coreline{margin:.9em auto 0;font-size:1.02rem;color:var(--grow);border:1px solid var(--grow);border-radius:9px;padding:.4em 1em;max-width:64ch}
h2{font-size:1.55rem;color:var(--ac);margin:.2em 0 .45em;border-bottom:2px solid var(--bd);padding-bottom:.3em}
.utitle{font-size:1.45rem;color:var(--fg);border-bottom:2px solid var(--bd)}
ul{font-size:1.05rem;line-height:1.55;max-width:88ch}li{margin:.3em 0}
.lede{font-size:1.15rem;max-width:88ch;margin:.2em 0 .6em;line-height:1.5}
.snote{color:var(--mut);font-size:.92rem;max-width:88ch}
.slide[data-type=section] h2{font-size:2rem;border:0;color:var(--fg)}
.prose{font-size:1.07rem;line-height:1.62;max-width:88ch;margin:.35em 0;white-space:pre-line}
.lprose{font-size:1.12rem;font-weight:600}
.aintro{text-align:left}
.mmd{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:1em;margin-top:.6em;text-align:center;max-width:110ch;overflow:auto;max-height:66vh}
.mmd svg{max-width:100%;max-height:60vh;width:auto;height:auto}
/* mechanism slides exist FOR the diagram — give it the room */
.slide[data-type=lesson-mech] .mmd{max-height:74vh}
.slide[data-type=lesson-mech] .mmd svg{max-height:68vh}
.mmdwait{color:var(--mut)}.mmderr{color:#ff6b6b;text-align:left;white-space:pre-wrap;font-family:monospace}
.mechwrap{max-width:110ch}
/* unit header strip */
.uhead{display:flex;flex-wrap:wrap;gap:.6em;align-items:center;font-size:.82rem;color:var(--mut);margin-bottom:.4em}
.uact{font-weight:700}
.uwhat{font-weight:700;color:var(--fg)}
.ucount{margin-left:auto}
.ubeats .bcrumb{padding:.1em .55em;border:1px solid var(--bd);border-radius:10px;margin-left:.3em}
.ubeats .bcrumb.on{border-color:var(--ac);color:var(--ac);font-weight:700}
.corebadge{border:1px solid var(--grow);color:var(--grow);font-size:.68rem;font-weight:800;padding:.08em .55em;border-radius:9px;letter-spacing:.06em;text-transform:uppercase}
/* beats */
.beat{background:var(--card);border:1px solid var(--bd);border-left:4px solid var(--bd);border-radius:8px;padding:.7em 1em;margin:.5em 0;max-width:96ch}
.beat-fail{border-left-color:var(--fail)} .beat-lesson{border-left-color:var(--lesson)}
.beat-grow{border-left-color:var(--grow)} .beat-aigp{border-left-color:var(--aigp)}
.btag{display:inline-block;font-size:.74rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;margin-bottom:.25em}
.tfail{color:var(--fail)} .tlesson{color:var(--lesson)} .tgrow{color:var(--grow)} .taigp{color:var(--aigp)} .tmech{color:var(--mech)}
.evidence{color:var(--mut);font-size:.84rem;font-family:ui-monospace,Consolas,monospace;margin-top:.45em}
.thinkbox{border:1px dashed var(--ac);border-radius:8px;padding:.6em 1em;margin:.6em 0;max-width:96ch}
.tb-cap{color:var(--ac);font-size:.78rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
.tb-q{font-size:1.08rem;font-style:italic;margin:.3em 0 0}
.takeaway{background:#1c2230;border:1px solid var(--aigp);border-radius:8px;padding:.55em .9em;margin-top:.6em;font-size:1.05rem;font-weight:600;max-width:92ch}
.tk-cap{color:var(--aigp);font-size:.74rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;display:block}
/* stats */
.statrow{display:flex;flex-wrap:wrap;gap:1em;margin:.65em 0 .2em}
.stat{display:flex;flex-direction:column;align-items:flex-start;background:#10151c;border:1px solid var(--bd);border-radius:10px;padding:.5em .9em}
.svrow{display:flex;align-items:baseline;gap:.45em}
.sv{font-size:1.5rem;font-weight:800;color:var(--fg);font-variant-numeric:tabular-nums}
.svbefore{color:var(--mut);font-size:1.25rem}
.sarrow{color:var(--grow);font-size:1.2rem;font-weight:800}
.slabel{color:var(--mut);font-size:.8rem;margin-top:.18em}
.methodstrip{display:flex;flex-wrap:wrap;gap:.45em;align-items:center;margin:.7em 0 .9em;max-width:96ch}
.ms{border:1.5px solid var(--bd);border-radius:9px;padding:.42em .85em;font-size:.98rem;font-weight:700;background:var(--card)}
.msarrow{color:var(--mut);font-size:1.15rem}
.chiprow{display:flex;flex-wrap:wrap;gap:.35em;margin:.35em 0}
.dchip{border:1px solid var(--aigp);color:#c5b3f0;font-size:.78rem;padding:.12em .6em;border-radius:12px}
.fchip{border:1px solid var(--ac);color:#a8cdf5;font-size:.78rem;padding:.12em .6em;border-radius:12px}
.studied-btn{margin-top:.8em;background:var(--card);color:var(--fg);border:1px solid var(--bd);border-radius:8px;padding:.45em 1.1em;font-size:.95rem;cursor:pointer;align-self:flex-start}
.studied-btn.on{border-color:var(--grow);color:var(--grow);font-weight:700}
/* act cards */
.actcard{max-width:96ch;background:var(--card);border:1px solid var(--bd);border-left:6px solid var(--bd);border-radius:12px;padding:1.1em 1.6em 1.3em;text-align:left}
.actkicker{font-size:.95rem;letter-spacing:.04em;text-transform:uppercase;font-weight:700}
/* index */
#indexbox{max-width:118ch;overflow-y:auto;width:100%}
.idxlegend{color:var(--mut);font-size:.86rem;margin:.1em 0 .6em}
.idxlegend .corebadge{margin:0 .25em}
.idxgroup{margin:.5em 0 .9em;text-align:left}
.idxgroup h3{font-size:1.02rem;margin:.2em 0 .35em}
.idxitems{display:flex;flex-wrap:wrap;gap:.3em}
.idxchip{border:1px solid var(--bd);border-radius:7px;padding:.18em .55em;font-size:.8rem;cursor:pointer;background:var(--card);color:var(--fg);max-width:34ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.idxchip b{color:var(--ac);margin-right:.35em}
.idxchip.core{box-shadow:inset 3px 0 0 var(--grow)}
.idxchip.dim{opacity:.42}
.idxchip.done{border-color:var(--grow)}
.idxchip.done b{color:var(--grow)}
.idxchip.done::after{content:" \\2713";color:var(--grow);font-weight:800}
/* journey rail */
#rail{position:fixed;top:0;left:0;right:0;height:5px;display:flex;z-index:6}
.railseg{height:5px;opacity:.28}
.railseg.cur{opacity:1}
#bar{position:fixed;bottom:0;left:0;right:0;display:flex;justify-content:space-between;align-items:center;gap:1em;padding:.45em 1.2em;background:#010409cc;border-top:1px solid var(--bd);font-size:.84rem;color:var(--mut)}
#bar b{color:var(--ac)}
#modebtn{background:var(--card);color:var(--grow);border:1px solid var(--grow);border-radius:7px;padding:.18em .7em;font-size:.8rem;cursor:pointer;font-weight:700}
#modebtn.full{color:var(--ac);border-color:var(--ac)}
kbd{background:var(--card);border:1px solid var(--bd);border-radius:4px;padding:.06em .38em}
#auditout{display:none}
</style></head><body>
<div id="rail"></div>
<div id="deck">__SLIDES__</div>
<div id="bar">
<span id="barleft">BlarAI — what building it taught</span>
<span style="display:flex;align-items:center;gap:.8em"><button id="modebtn" onclick="toggleMode()"></button>
<span id="studcount"></span> &middot; <kbd>&larr;</kbd><kbd>&rarr;</kbd> slide &middot; <kbd>n</kbd>/<kbd>p</kbd> lesson &middot; <kbd>c</kbd> mode &middot; <kbd>i</kbd> index &middot; <b><span id="cur">1</span></b>/<span id="tot">1</span></span>
</div>
<pre id="auditout"></pre>
<script>
const MMD = __MMD__;
const IDX = __IDX__;
const RAIL = __RAIL__;
const N_UNITS = __NUNITS__;
const CORE_COUNT = __NCORE__;
const Q = new URLSearchParams(location.search);
const TESTMODE = Q.get('audit') || Q.get('selftest');
const KEY = TESTMODE ? 'blarai_lessons_deck_test' : 'blarai_lessons_deck_v1';
const CORESET = new Set(IDX.flatMap(g => g.items.filter(it => it.c).map(it => it.uid)));
mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'loose',
  themeVariables:{fontSize:'17px'},
  flowchart:{useMaxWidth:false,nodeSpacing:34,rankSpacing:30},
  sequence:{useMaxWidth:false}});
async function renderAll(){
  for (const [id, code] of MMD) {
    const host = document.getElementById(id);
    if (!host) continue;
    try {
      const { svg } = await mermaid.render(id + '_svg', code); host.innerHTML = svg;
      let el = host.querySelector('svg');
      let vb = el && el.viewBox && el.viewBox.baseVal;
      // Auto-orient: a skinny vertical chain (much taller than wide) wastes a
      // 16:9 card and forces deep scrolling — re-render it left-to-right.
      if (vb && vb.height > 1.9 * vb.width && code.trim().startsWith('flowchart TD')) {
        try {
          const alt = await mermaid.render(id + '_svgL', code.replace('flowchart TD', 'flowchart LR'));
          host.innerHTML = alt.svg;
          el = host.querySelector('svg'); vb = el.viewBox.baseVal;
        } catch (e2) { /* keep the TD render */ }
      }
      // Readability floor: contain-fit must never shrink a diagram into dust —
      // below 0.7 of natural size the card scrolls the remainder instead.
      if (vb && vb.height > 0) el.style.minHeight = Math.round(vb.height * 0.7) + 'px';
    }
    catch (e) { host.innerHTML = '<div class="mmderr">Diagram failed to render:\\n' + (e && e.message ? e.message : e) + '</div>'; }
  }
}
const READY = renderAll();
const S=[...document.querySelectorAll('.slide')];let i=0;
function state(){ try { return JSON.parse(localStorage.getItem(KEY)||'{}'); } catch(e){ return {}; } }
function save(st){ try { localStorage.setItem(KEY, JSON.stringify(st)); } catch(e){} }
function studiedSet(){ return state().studied || {}; }
let MODE = state().mode || 'core';
function navigable(k){
  const sl=S[k]; if(!sl) return false;
  if(!sl.dataset.unit) return true;
  return MODE==='full' || sl.dataset.core==='1';
}
function toggleStudied(uid){
  const st = state(); st.studied = st.studied || {};
  if (st.studied[uid]) delete st.studied[uid]; else st.studied[uid] = 1;
  save(st); paintStudied();
}
function paintStudied(){
  const st = studiedSet();
  document.querySelectorAll('.idxchip').forEach(c=>c.classList.toggle('done', !!st[c.dataset.uid]));
  document.querySelectorAll('.studied-btn').forEach(b=>{
    const uid = b.closest('.slide').dataset.unit;
    const on = !!st[uid];
    b.classList.toggle('on', on);
    b.textContent = on ? 'Studied — click to unmark' : 'Mark studied';
  });
  const done = Object.keys(st);
  const coreDone = done.filter(u=>CORESET.has(u)).length;
  document.getElementById('studcount').textContent = coreDone + '/' + CORE_COUNT + ' core · ' + done.length + '/' + N_UNITS + ' studied';
}
function setMode(m){
  MODE = m;
  const st = state(); st.mode = m; save(st);
  const btn = document.getElementById('modebtn');
  btn.textContent = m==='core' ? ('core path · ' + CORE_COUNT + ' lessons') : ('full deck · ' + N_UNITS + ' units');
  btn.classList.toggle('full', m==='full');
  document.querySelectorAll('.idxchip').forEach(ch=>ch.classList.toggle('dim', m==='core' && !CORESET.has(ch.dataset.uid)));
}
function toggleMode(){ setMode(MODE==='core' ? 'full' : 'core'); }
function buildIndex(){
  const box = document.getElementById('indexbox');
  box.innerHTML = '<div class="idxlegend">Green-edged chips are the <span class="corebadge">core path</span>; in core mode the rest are dimmed but still clickable. A check means studied.</div>' + IDX.map(g =>
    '<div class="idxgroup"><h3 style="color:'+g.color+'">' + g.name + '</h3><div class="idxitems">' +
    g.items.map(it => '<span class="idxchip'+(it.c?' core':'')+'" data-uid="'+it.uid+'" data-slide="'+it.s+'" title="'+it.t.replace(/"/g,'&quot;')+'"><b>'+it.n+'</b>'+it.t+'</span>').join('') +
    '</div></div>').join('');
  box.querySelectorAll('.idxchip').forEach(c=>c.addEventListener('click',()=>show(parseInt(c.dataset.slide))));
}
function buildRail(){
  const r = document.getElementById('rail');
  const total = RAIL.reduce((a,g)=>a+g.n,0);
  r.innerHTML = RAIL.map(g=>'<span class="railseg" data-name="'+g.name+'" style="background:'+g.color+';flex-grow:'+(g.n/total)+'"></span>').join('');
}
function paintRail(act){
  document.querySelectorAll('.railseg').forEach(s=>s.classList.toggle('cur', !!act && act.indexOf(s.dataset.name)===0));
}
const tot=document.getElementById('tot');tot.textContent=S.length;
function show(n){
  i=Math.max(0,Math.min(S.length-1,n));
  S.forEach((s,k)=>s.classList.toggle('active',k===i));
  document.getElementById('cur').textContent=i+1;
  const sl=S[i];
  const left='BlarAI — what building it taught' + (sl.dataset.act ? ' &middot; <b>'+sl.dataset.act+'</b>' : '') +
    (sl.dataset.unitidx!==undefined && sl.dataset.unit ? ' &middot; unit '+(parseInt(sl.dataset.unitidx)+1)+'/'+N_UNITS : '');
  document.getElementById('barleft').innerHTML=left;
  paintRail(sl.dataset.act||'');
  try { history.replaceState(null,'',' #'+(i+1)); } catch(e){}
  const st=state(); st.last=i; save(st);
  S[i].scrollTop=0;
}
function nextNav(d){
  let k=i+d;
  while(k>=0 && k<S.length && !navigable(k)) k+=d;
  if(k>=0 && k<S.length && navigable(k)) show(k);
}
function unitStarts(){ const out=[]; S.forEach((s,k)=>{ if(s.dataset.unit && (k===0 || S[k-1].dataset.unit!==s.dataset.unit)) out.push(k); }); return out; }
const US=unitStarts();
function nextUnit(d){
  const starts = US.filter(k=>navigable(k));
  if(d>0){ for(const k of starts){ if(k>i) return show(k); } return show(S.length-1); }
  let prev=null; for(const k of starts){ if(k<i) prev=k; else break; } return show(prev===null?0:prev);
}
addEventListener('keydown',e=>{
  if(['ArrowRight','PageDown',' '].includes(e.key)){nextNav(1);e.preventDefault()}
  else if(['ArrowLeft','PageUp'].includes(e.key)){nextNav(-1);e.preventDefault()}
  else if(e.key==='n'){nextUnit(1);e.preventDefault()}
  else if(e.key==='p'){nextUnit(-1);e.preventDefault()}
  else if(e.key==='c'){toggleMode();e.preventDefault()}
  else if(e.key==='i'){show(__IDXSLIDE__);e.preventDefault()}
  else if(e.key==='Home'){show(0);e.preventDefault()}
});
buildIndex(); buildRail(); setMode(MODE); paintStudied();
const h=parseInt(location.hash.slice(1));
show(h ? h-1 : (TESTMODE ? 0 : (state().last || 0)));
/* ---------------- test hooks (driven headless by run_checks.py) ----------- */
function emit(report){
  const out = document.getElementById('auditout');
  out.textContent = JSON.stringify(report, null, 1);
  document.title = (report.pass ? 'AUDIT:PASS' : 'AUDIT:FAIL') + ':' + (report.summary || '');
}
async function runAudit(){
  await READY;
  const rep = {kind:'audit', slides:S.length, units:N_UNITS, diagrams:MMD.length,
               viewport:[innerWidth, innerHeight],
               rendered_svgs:0, mmd_errors:[], paint_spills:[], h_overflow:[],
               extreme_v_overflow:[], shrunk:[], scrolly:[]};
  const prevMode = MODE; MODE = 'full';
  for(let k=0;k<S.length;k++){
    show(k);
    const sl=S[k];
    const slr = sl.getBoundingClientRect();
    sl.querySelectorAll('.mmderr').forEach(()=>rep.mmd_errors.push(k));
    sl.querySelectorAll('.mmd').forEach(m=>{
      const svg=m.querySelector('svg'); if(!svg) return;
      rep.rendered_svgs++;
      // The .mmd card clips (overflow:auto) and the svg is contain-fit via CSS,
      // so the correct paint check is the svg LAYOUT box escaping its card —
      // not child ink below a scrollable fold (the v1 false-positive class).
      const mr=m.getBoundingClientRect();
      const r=svg.getBoundingClientRect();
      // A clipping card (overflow auto/hidden) can never paint over later
      // content — escape is only a SPILL when the card's overflow is visible
      // (the capstone bug class). Clipped excess is the in-card scroll metric.
      const clips = getComputedStyle(m).overflowY !== 'visible';
      const escY = Math.round(r.bottom-mr.bottom), escX = Math.round(r.right-mr.right);
      if(!clips && (escY>4 || escX>4 || r.top<mr.top-4 || r.left<mr.left-4))
        rep.paint_spills.push({slide:k, d:[escX, escY]});
      if(clips && escY>4) rep.scrolly.push({slide:k, extra:escY});
      const vb=svg.viewBox && svg.viewBox.baseVal;
      if(vb && vb.height>0){ const sc=r.height/vb.height; if(sc<0.65) rep.shrunk.push({slide:k, scale:Math.round(sc*100)/100}); }
    });
    if(sl.scrollWidth > sl.clientWidth+8) rep.h_overflow.push(k);
    if(sl.scrollHeight > sl.clientHeight*1.95) rep.extreme_v_overflow.push(k);
  }
  MODE = prevMode;
  rep.pass = !rep.mmd_errors.length && !rep.paint_spills.length && !rep.h_overflow.length
             && !rep.shrunk.length && rep.rendered_svgs===MMD.length;
  rep.summary = 'svgs='+rep.rendered_svgs+'/'+MMD.length+' spills='+rep.paint_spills.length
              + ' hov='+rep.h_overflow.length+' err='+rep.mmd_errors.length
              + ' xv='+rep.extreme_v_overflow.length+' shrunk='+rep.shrunk.length
              + ' scrolly='+rep.scrolly.length;
  show(0);
  emit(rep);
}
async function runSelftest(){
  await READY;
  const fails=[];
  function ok(name,cond){ if(!cond) fails.push(name); }
  try{
    ok('slide-count-sane', S.length>200);
    show(7); ok('show-jumps', i===7);
    setMode('full'); nextUnit(1); ok('nextUnit-advances', i>7 && S[i].dataset.unit);
    const before=!!studiedSet()['L2'];
    toggleStudied('L2'); ok('studied-toggles-on', !!studiedSet()['L2']!==before);
    toggleStudied('L2'); ok('studied-toggles-back', !!studiedSet()['L2']===before);
    setMode('core');
    ok('core-nav-only-core', US.filter(k=>navigable(k)).every(k=>S[k].dataset.core==='1'));
    ok('core-count-matches', US.filter(k=>navigable(k)).length===CORE_COUNT);
    setMode('full');
    ok('full-count-matches', US.filter(k=>navigable(k)).length===N_UNITS);
    ok('index-groups', document.querySelectorAll('.idxgroup').length===IDX.length);
    ok('index-chips', document.querySelectorAll('.idxchip').length===N_UNITS);
    ok('rail-segments', document.querySelectorAll('.railseg').length===RAIL.length);
    show(12); ok('resume-recorded', state().last===12);
    show(0);
  }catch(e){ fails.push('exception:'+(e&&e.message?e.message:e)); }
  emit({kind:'selftest', pass:!fails.length, fails:fails, summary:'fails='+fails.length});
}
if(Q.get('audit')) runAudit();
if(Q.get('selftest')) runSelftest();
</script></body></html>"""

title_slide = (
    '<div class="titlebox"><h1>What building BlarAI taught — one lesson at a time</h1>'
    f'<p class="subtitle">{TOTAL_NUMBERED} numbered lessons + the {N_FRAG}-unit June 2026 arc, each taught from its real failure, through the AIGP lens</p>'
    f'<p class="meta">Source: LESSONS.md + BUILD_JOURNAL.md and docs/journal_fragments/ &middot; AIGP = Artificial Intelligence Governance Professional (IAPP) &middot; Body of Knowledge v2.1 vocabulary &middot; honest by design: the failures stay in</p>'
    f'<p class="coreline">Opens on the {len(CORE)}-lesson core path — the most governance-loaded lessons, 2&ndash;3 hours of study. Press <b>c</b> for the full {N_UNITS}-unit archive.</p></div>'
)
slides.insert(0, f'<section class="slide" data-type="title" data-act="">{title_slide}</section>')
# All recorded slide indices shift by exactly one (the title insert).
unit_first_slide = {k: v + 1 for k, v in unit_first_slide.items()}
for g in index_groups:
    for it in g["items"]:
        it["s"] += 1
INDEX_SLIDE_NO = 3  # 0-based: title=0, howto=1, frame=2, index=3

out = (
    TEMPLATE.replace("__TITLE__", "BlarAI Lessons — the teaching deck")
    .replace("__SLIDES__", "\n".join(slides))
    .replace("__MMD__", json.dumps(DIAGRAMS))
    .replace("__IDX__", json.dumps(index_groups))
    .replace("__RAIL__", json.dumps(RAILDATA))
    .replace("__NUNITS__", str(N_UNITS))
    .replace("__NCORE__", str(len(CORE)))
    .replace("__IDXSLIDE__", str(INDEX_SLIDE_NO))
)
(D / "lessons_deck.html").write_text(out, encoding="utf-8")

# Post-build assertions (cheap structural self-checks).
expected_slides = 1 + 3 + 1 + 8 + 3 * N_UNITS + N_DIAG_UNITS + 1
assert len(slides) == expected_slides, f"slide count {len(slides)} != expected {expected_slides}"
assert len(unit_first_slide) == N_UNITS
assert len(DIAGRAMS) == N_DIAG_UNITS + 1, "every unit diagram + the domains map must be registered"
print(f"wrote lessons_deck.html: {len(slides)} slides, {N_UNITS} units "
      f"({TOTAL_NUMBERED} numbered + {N_FRAG} June), {len(DIAGRAMS)} diagrams, core path {len(CORE)}")
