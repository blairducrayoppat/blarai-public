"""#840 — the live-proof dashboard generator (scaffold).

Reads (a) an optional Section-A evidence data JSON and (b) the accumulating
``battery-summary.json`` history, and writes ONE self-contained, theme-aware HTML dashboard
with two sections and a cockpit-friendly single-file output:

* **Section A — "Proof"**: the ADR-037 Tier-1 acceptance demos. Each gate renders
  input → machinery response → CAUGHT/PASS + a real evidence excerpt. Every demo driver is
  a clearly-marked STUB at scaffold time (see :mod:`demo_registry`) — no fabricated evidence.
* **Section B — "Grading Health"**: night-over-night trends from the battery-summary history
  (verdict mix, FALSE-DONE/interventions honesty invariants, guest-oracle agreement, and the
  advisory #827/#832/#837 blocks with a graceful empty state until the classifiers wire in).

Design constraints (all honored): SELF-CONTAINED (all CSS/JS inline, no external requests,
no network), THEME-AWARE (prefers-color-scheme + a data-theme override toggle), a favicon,
responsive, wide content scrolls in its own container. DETERMINISTIC: same inputs → same
bytes (the "generated" stamp is derived from the data / an explicit --generated-at, never
wall-clock).

Usage:
    python scripts/live_proof/generate_dashboard.py [--battery-dir DIR] [--evidence FILE]
        [--out FILE] [--generated-at STAMP] [--open]

Palette: the dataviz reference categorical + status palette (validated for light & dark;
verdict marks always ship with a label + count so a status color never carries meaning alone).
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

# Import sibling scaffold modules whether run as a script or imported as part of a package.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from battery_reader import (  # noqa: E402
    BAND_ORDER,
    FAILURE_CLASS_ORDER,
    GREEN_CLASS_ORDER,
    GUEST_AGREEMENT_ORDER,
    VERDICT_ORDER,
    HistorySummary,
    NightRecord,
    read_history,
    summarize,
)
from demo_registry import DemoResult, collect_demo_results  # noqa: E402

DEFAULT_OUT = _HERE / "grading_health_dashboard.html"

# Verdict → palette-role mapping (dataviz reference palette; validated both modes). GREEN =
# good, PARKED = categorical blue, RECOVERED = categorical violet, STALLED = status warning,
# FALSE-DONE = status critical. Every verdict is ALWAYS rendered with its label + count.
_VERDICT_CSSVAR = {
    "GREEN": "--v-green",
    "PARKED-HONEST": "--v-parked",
    "RECOVERED": "--v-recovered",
    "STALLED": "--v-stalled",
    "FALSE-DONE": "--v-false-done",
}
_VERDICT_LABEL = {
    "GREEN": "GREEN",
    "PARKED-HONEST": "PARKED-HONEST",
    "RECOVERED": "RECOVERED",
    "STALLED": "STALLED",
    "FALSE-DONE": "FALSE-DONE",
}


def esc(text: object) -> str:
    return escape(str(text), quote=True)


# ---------------------------------------------------------------------------
# CSS + JS (static; kept out of f-strings so CSS braces are literal)
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --page: #f9f9f7;
  --surface-1: #fcfcfb;
  --surface-2: #f2f1ee;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #6f6e69;
  --gridline: #e1e0d9;
  --baseline: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --shadow: 0 1px 2px rgba(11,11,11,0.06), 0 2px 8px rgba(11,11,11,0.04);

  --v-green: #0ca30c;
  --v-parked: #2a78d6;
  --v-recovered: #4a3aa7;
  --v-stalled: #fab219;
  --v-false-done: #d03b3b;

  --good: #0ca30c;
  --warning: #fab219;
  --serious: #ec835a;
  --critical: #d03b3b;

  --band-a: #0ca30c;
  --band-b: #fab219;
  --band-c: #ec835a;

  --pill-live-bg: rgba(12,163,12,0.14);
  --pill-live-fg: #0a7a0a;
  --pill-staged-bg: rgba(250,178,25,0.18);
  --pill-staged-fg: #8a5a00;
  --pill-planned-bg: rgba(42,120,214,0.12);
  --pill-planned-fg: #1c5cab;
  --pill-stub-bg: rgba(111,110,105,0.14);
  --pill-stub-fg: #52514e;
}
:root[data-theme="dark"] {
  --page: #0d0d0d;
  --surface-1: #1a1a19;
  --surface-2: #232321;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --muted: #a3a29b;
  --gridline: #2c2c2a;
  --baseline: #383835;
  --border: rgba(255,255,255,0.12);
  --shadow: none;

  --v-green: #0ca30c;
  --v-parked: #3987e5;
  --v-recovered: #9085e9;
  --v-stalled: #fab219;
  --v-false-done: #e05a5a;

  --good: #0ca30c;
  --warning: #fab219;
  --serious: #ec835a;
  --critical: #e05a5a;

  --band-a: #0ca30c;
  --band-b: #fab219;
  --band-c: #ec835a;

  --pill-live-bg: rgba(12,163,12,0.20);
  --pill-live-fg: #34c634;
  --pill-staged-bg: rgba(250,178,25,0.20);
  --pill-staged-fg: #fab219;
  --pill-planned-bg: rgba(57,135,229,0.20);
  --pill-planned-fg: #7fb2f0;
  --pill-stub-bg: rgba(163,162,155,0.18);
  --pill-stub-fg: #c3c2b7;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --page: #0d0d0d;
    --surface-1: #1a1a19;
    --surface-2: #232321;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #a3a29b;
    --gridline: #2c2c2a;
    --baseline: #383835;
    --border: rgba(255,255,255,0.12);
    --shadow: none;
    --v-parked: #3987e5;
    --v-recovered: #9085e9;
    --v-false-done: #e05a5a;
    --critical: #e05a5a;
    --pill-live-bg: rgba(12,163,12,0.20);
    --pill-live-fg: #34c634;
    --pill-staged-bg: rgba(250,178,25,0.20);
    --pill-staged-fg: #fab219;
    --pill-planned-bg: rgba(57,135,229,0.20);
    --pill-planned-fg: #7fb2f0;
    --pill-stub-bg: rgba(163,162,155,0.18);
    --pill-stub-fg: #c3c2b7;
  }
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1120px; margin: 0 auto; padding: 24px 20px 80px; }
a { color: var(--v-parked); }

header.top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
header.top h1 { font-size: 22px; margin: 0 0 2px; letter-spacing: -0.01em; }
header.top .sub { color: var(--text-secondary); font-size: 13.5px; margin: 0; max-width: 68ch; }
.asof { color: var(--muted); font-size: 12.5px; margin-top: 6px; }

.theme-toggle {
  border: 1px solid var(--border); background: var(--surface-1); color: var(--text-secondary);
  border-radius: 999px; padding: 7px 13px; font-size: 13px; cursor: pointer; white-space: nowrap;
}
.theme-toggle:hover { color: var(--text-primary); }

.banner {
  margin: 18px 0 8px; border: 1px solid var(--border); border-left: 3px solid var(--v-parked);
  background: var(--surface-1); border-radius: 10px; padding: 12px 15px; font-size: 13.5px;
  color: var(--text-secondary);
}
.banner strong { color: var(--text-primary); }

h2.section { font-size: 17px; margin: 34px 0 4px; letter-spacing: -0.01em; }
h2.section .tag { font-size: 12px; color: var(--muted); font-weight: 400; }
p.lead { color: var(--text-secondary); font-size: 13.5px; margin: 4px 0 16px; max-width: 74ch; }

.pill {
  display: inline-block; border-radius: 999px; padding: 2px 9px; font-size: 11px;
  font-weight: 600; letter-spacing: 0.02em; vertical-align: middle;
}
.pill.live { background: var(--pill-live-bg); color: var(--pill-live-fg); }
.pill.staged { background: var(--pill-staged-bg); color: var(--pill-staged-fg); }
.pill.planned { background: var(--pill-planned-bg); color: var(--pill-planned-fg); }
.pill.stub { background: var(--pill-stub-bg); color: var(--pill-stub-fg); }
.pill.caught { background: var(--pill-live-bg); color: var(--pill-live-fg); }
.pill.advisory { background: var(--pill-planned-bg); color: var(--pill-planned-fg); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; }
.card {
  border: 1px solid var(--border); background: var(--surface-1); border-radius: 12px;
  padding: 15px 16px; box-shadow: var(--shadow);
}
.card .gid { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.card h3 { font-size: 14.5px; margin: 3px 0 8px; }
.card .pills { margin: 0 0 10px; display: flex; gap: 6px; flex-wrap: wrap; }
.kv { font-size: 12.5px; margin: 7px 0; }
.kv .k { color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; font-size: 10.5px; display: block; }
.kv .v { color: var(--text-secondary); }
.flow { border-top: 1px solid var(--gridline); margin-top: 10px; padding-top: 9px; }
.flow .step { font-size: 12.5px; margin: 5px 0; color: var(--text-secondary); }
.flow .step .lbl { color: var(--muted); font-weight: 600; }
.evidence {
  margin-top: 10px; border-radius: 8px; background: var(--surface-2); border: 1px dashed var(--border);
  padding: 9px 11px; font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
  font-size: 11.5px; color: var(--text-secondary); overflow-x: auto; white-space: pre;
}
.evidence.empty { font-family: system-ui, sans-serif; font-style: italic; white-space: normal; }
.honesty { margin-top: 9px; font-size: 11.5px; color: var(--muted); border-top: 1px solid var(--gridline); padding-top: 8px; }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; margin: 6px 0 8px; }
.tile { border: 1px solid var(--border); background: var(--surface-1); border-radius: 12px; padding: 14px 16px; box-shadow: var(--shadow); }
.tile .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.tile .num { font-size: 30px; font-weight: 650; letter-spacing: -0.02em; margin: 2px 0 1px; }
.tile .num.good { color: var(--good); }
.tile .num.warn { color: var(--warning); }
.tile .num.crit { color: var(--critical); }
.tile .note { font-size: 12px; color: var(--text-secondary); }
.dotstrip { margin-top: 8px; display: flex; gap: 3px; flex-wrap: wrap; }
.dot { width: 9px; height: 9px; border-radius: 2px; }
.dot.ok { background: var(--good); }
.dot.bad { background: var(--critical); }

.chart-card { border: 1px solid var(--border); background: var(--surface-1); border-radius: 12px; padding: 16px; box-shadow: var(--shadow); margin: 14px 0; }
.chart-card h3 { font-size: 14px; margin: 0 0 2px; }
.chart-card .cap { font-size: 12.5px; color: var(--text-secondary); margin: 0 0 12px; max-width: 76ch; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 0 0 10px; font-size: 12px; color: var(--text-secondary); }
.legend .item { display: inline-flex; align-items: center; gap: 6px; }
.legend .sw { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
.scrollx { overflow-x: auto; }
svg .axis { stroke: var(--baseline); }
svg .grid { stroke: var(--gridline); }
svg text { fill: var(--muted); font-size: 10px; font-family: system-ui, sans-serif; }
svg .seg { stroke: var(--surface-1); stroke-width: 2; }

.empty-state {
  border: 1px dashed var(--border); border-radius: 10px; background: var(--surface-2);
  padding: 14px 16px; color: var(--text-secondary); font-size: 13px;
}
.empty-state .h { color: var(--text-primary); font-weight: 600; display: block; margin-bottom: 3px; }

table.data { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
table.data th, table.data td { text-align: right; padding: 5px 9px; border-bottom: 1px solid var(--gridline); }
table.data th:first-child, table.data td:first-child { text-align: left; }
table.data th { color: var(--muted); font-weight: 600; position: sticky; top: 0; background: var(--surface-1); }
details.tableview { margin-top: 10px; }
details.tableview summary { cursor: pointer; font-size: 12.5px; color: var(--v-parked); }

footer.foot { margin-top: 44px; border-top: 1px solid var(--gridline); padding-top: 16px; color: var(--muted); font-size: 12px; }
footer.foot code { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; font-size: 11.5px; }
footer.foot .legendkey { margin: 8px 0; }

#tooltip {
  position: fixed; z-index: 50; pointer-events: none; opacity: 0; transition: opacity .08s;
  background: var(--text-primary); color: var(--page); font-size: 11.5px; padding: 5px 8px;
  border-radius: 6px; max-width: 260px; box-shadow: 0 2px 10px rgba(0,0,0,0.25);
}
"""

_JS = """
(function () {
  var root = document.documentElement;
  function apply(t) { if (t) { root.setAttribute('data-theme', t); } else { root.removeAttribute('data-theme'); } }
  try { var saved = localStorage.getItem('liveproof-theme'); if (saved) apply(saved); } catch (e) {}
  function current() {
    var attr = root.getAttribute('data-theme');
    if (attr) return attr;
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }
  var btn = document.getElementById('theme-toggle');
  if (btn) btn.addEventListener('click', function () {
    var next = current() === 'dark' ? 'light' : 'dark';
    apply(next);
    try { localStorage.setItem('liveproof-theme', next); } catch (e) {}
    btn.textContent = next === 'dark' ? 'Light theme' : 'Dark theme';
  });

  var tip = document.getElementById('tooltip');
  function show(e, html) { if (!tip) return; tip.innerHTML = html; tip.style.opacity = '1';
    var x = e.clientX + 12, y = e.clientY + 12;
    if (x + 270 > window.innerWidth) x = e.clientX - 260;
    tip.style.left = x + 'px'; tip.style.top = y + 'px'; }
  function hide() { if (tip) tip.style.opacity = '0'; }
  document.querySelectorAll('[data-tip]').forEach(function (el) {
    el.addEventListener('mousemove', function (e) { show(e, el.getAttribute('data-tip')); });
    el.addEventListener('mouseleave', hide);
  });
})();
"""


# ---------------------------------------------------------------------------
# Favicon (emoji in an inline SVG data URI — no external request)
# ---------------------------------------------------------------------------

def _favicon() -> str:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
           "<text x='50' y='54' font-size='74' text-anchor='middle' "
           "dominant-baseline='central'>\U0001F6E1️</text></svg>")
    from urllib.parse import quote
    return "data:image/svg+xml," + quote(svg)


# ---------------------------------------------------------------------------
# Section A — the Proof gate cards
# ---------------------------------------------------------------------------

def _build_pill(status: str) -> str:
    cls = {"LIVE": "live", "STAGED": "staged", "PLANNED": "planned"}.get(status, "planned")
    return f'<span class="pill {cls}">BUILD: {esc(status)}</span>'


def _demo_pill(status: str, wired: bool) -> str:
    if status == "STUB" or not wired:
        return '<span class="pill stub">DEMO: STUB (not wired)</span>'
    if status in ("CAUGHT", "PASS"):
        return f'<span class="pill caught">DEMO: {esc(status)}</span>'
    return f'<span class="pill staged">DEMO: {esc(status)}</span>'


def _demo_card(r: DemoResult) -> str:
    s = r.spec
    pills = [_build_pill(s.build_status), _demo_pill(r.status, r.wired)]
    if s.advisory:
        pills.append('<span class="pill advisory">ADVISORY-ONLY</span>')
    if r.wired and r.evidence_excerpt:
        ev = f'<div class="evidence">{esc(r.evidence_excerpt)}</div>'
        if r.evidence_source:
            ev += f'<div class="honesty">Source: {esc(r.evidence_source)}</div>'
    else:
        ev = ('<div class="evidence empty">No evidence excerpt — this demo driver is a scaffold '
              'STUB. Nothing is fabricated here; the real driver quotes a live gate run once wired.</div>')
    return (
        '<div class="card">'
        f'<div class="gid">{esc(s.gate_id)} · {esc(s.ticket)}</div>'
        f'<h3>{esc(s.title)}</h3>'
        f'<div class="pills">{"".join(pills)}</div>'
        f'<div class="kv"><span class="k">Proves</span><span class="v">{esc(s.proves)}</span></div>'
        f'<div class="kv"><span class="k">Cannot prove</span><span class="v">{esc(s.cannot_prove)}</span></div>'
        '<div class="flow">'
        f'<div class="step"><span class="lbl">Input &rarr;</span> {esc(s.demo_scenario)}</div>'
        f'<div class="step"><span class="lbl">Machinery &rarr;</span> {esc(s.expected_response)}</div>'
        f'<div class="step"><span class="lbl">Target verdict &rarr;</span> {esc(s.expected_verdict)} '
        f'<span style="color:var(--muted)">(when wired)</span></div>'
        '</div>'
        f'{ev}'
        f'<div class="honesty">{esc(r.honesty_note)}</div>'
        '</div>'
    )


def _section_a(demo_results: list[DemoResult]) -> str:
    wired = sum(1 for r in demo_results if r.wired)
    total = len(demo_results)
    cards = "".join(_demo_card(r) for r in demo_results)
    return (
        '<h2 class="section">Section A &mdash; Proof '
        '<span class="tag">Tier-1 acceptance demos (ADR-037 gate ladder)</span></h2>'
        f'<p class="lead">Each gate demo feeds a concrete input to the machinery and shows the '
        f'response, the target verdict, and a real evidence excerpt from an actual gate run. '
        f'<strong>{wired} of {total} demo drivers are wired</strong>; the rest are clearly-marked '
        f'STUBs (the driver abstraction is built; the real drivers get filled in against live gate '
        f'runs). BUILD status is the gate’s presence in the codebase; DEMO status is whether '
        f'the demo itself is wired &mdash; a LIVE gate can still have a STUB demo, and the dashboard '
        f'never shows a stub as a pass.</p>'
        f'<div class="grid">{cards}</div>'
    )


# ---------------------------------------------------------------------------
# Section B — Grading Health trends
# ---------------------------------------------------------------------------

def _headline_tiles(summ: HistorySummary) -> str:
    n = summ.count
    fd = summ.any_false_done
    iv = summ.any_interventions
    fd_cls = "good" if fd == 0 else "crit"
    iv_cls = "good" if iv == 0 else "crit"
    green_rate = f"{summ.total_green}/{summ.total_eligible}" if summ.total_eligible else f"{summ.total_green}/0"

    def dots(pred_bad):
        return "".join(f'<span class="dot {"bad" if pred_bad(x) else "ok"}"></span>' for x in summ.nights)

    fd_dots = dots(lambda x: x.false_done > 0)
    iv_dots = dots(lambda x: x.interventions > 0)
    return (
        '<div class="tiles">'
        '<div class="tile">'
        f'<div class="label">FALSE-DONE (honesty invariant)</div>'
        f'<div class="num {fd_cls}">{fd}</div>'
        f'<div class="note">across {n} measured night(s). Target: 0 &mdash; a claimed-done without a '
        'passed oracle. A single non-zero is program-failing.</div>'
        f'<div class="dotstrip" aria-label="per-night FALSE-DONE">{fd_dots}</div>'
        '</div>'
        '<div class="tile">'
        f'<div class="label">Interventions</div>'
        f'<div class="num {iv_cls}">{iv}</div>'
        f'<div class="note">across {n} night(s). Target: 0 &mdash; the fleet grades unattended.</div>'
        f'<div class="dotstrip" aria-label="per-night interventions">{iv_dots}</div>'
        '</div>'
        '<div class="tile">'
        f'<div class="label">GREEN over plan-graph-eligible</div>'
        f'<div class="num">{esc(green_rate)}</div>'
        f'<div class="note">the honest denominator (#789): flat-queue jobs cannot GREEN by '
        'construction and are excluded, never hidden.</div>'
        '</div>'
        '<div class="tile">'
        f'<div class="label">Measured nights</div>'
        f'<div class="num">{n}</div>'
        f'<div class="note">real battery-summary/v1 records (dry-runs excluded).</div>'
        '</div>'
        '</div>'
    )


def _verdict_legend() -> str:
    items = []
    for v in VERDICT_ORDER:
        var = _VERDICT_CSSVAR[v]
        items.append(
            f'<span class="item"><span class="sw" style="background:var({var})"></span>'
            f'{esc(_VERDICT_LABEL[v])}</span>'
        )
    return f'<div class="legend">{"".join(items)}</div>'


def _svg_verdict_bars(nights: list[NightRecord]) -> str:
    """Inline SVG stacked-bar chart: one column per night, verdict counts stacked (job count
    on y). Deterministic; hover tooltips via data-tip. No external chart library."""
    if not nights:
        return '<div class="empty-state">No measured nights yet.</div>'
    col_w, gap = 30, 12
    pad_l, pad_r, pad_t, pad_b = 34, 10, 10, 46
    max_total = max((n.total for n in nights), default=0)
    y_max = max(max_total, 1)
    plot_h = 150
    height = pad_t + plot_h + pad_b
    width = pad_l + pad_r + len(nights) * col_w + (len(nights) - 1) * gap

    def y(v):  # value -> pixel
        return pad_t + plot_h - (v / y_max) * plot_h

    parts = [f'<svg role="img" width="{width}" height="{height}" viewBox="0 0 {width} {height}">']
    # y gridlines + ticks (integers up to y_max, capped ~5 ticks)
    ticks = y_max if y_max <= 6 else 6
    for i in range(ticks + 1):
        val = round(y_max * i / ticks)
        yy = y(val)
        parts.append(f'<line class="grid" x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{yy + 3:.1f}" text-anchor="end">{val}</text>')
    # baseline
    parts.append(f'<line class="axis" x1="{pad_l}" y1="{y(0):.1f}" x2="{width - pad_r}" y2="{y(0):.1f}"/>')

    x = pad_l
    for night in nights:
        base = 0
        for v in VERDICT_ORDER:
            c = night.verdicts.get(v, 0)
            if c <= 0:
                continue
            y_top = y(base + c)
            h = y(base) - y_top
            var = _VERDICT_CSSVAR[v]
            tip = f'{esc(night.label)}<br>{esc(_VERDICT_LABEL[v])}: {c}'
            parts.append(
                f'<rect class="seg" x="{x}" y="{y_top:.1f}" width="{col_w}" height="{max(h,0.5):.1f}" '
                f'rx="2" fill="var({var})" data-tip="{tip}"/>'
            )
            base += c
        # x label (MM-DD)
        lbl = night.date[5:] if night.date else night.label[-4:]
        cx = x + col_w / 2
        parts.append(
            f'<text x="{cx:.1f}" y="{pad_t + plot_h + 14}" text-anchor="end" '
            f'transform="rotate(-45 {cx:.1f} {pad_t + plot_h + 14})">{esc(lbl)}</text>'
        )
        x += col_w + gap
    parts.append('</svg>')
    return f'<div class="scrollx">{"".join(parts)}</div>'


def _night_table(nights: list[NightRecord]) -> str:
    head = ('<tr><th>Night</th><th>Total</th>'
            + "".join(f'<th>{esc(_VERDICT_LABEL[v])}</th>' for v in VERDICT_ORDER)
            + '<th>FALSE-DONE</th><th>Interv.</th><th>GREEN/elig</th></tr>')
    rows = []
    for nrec in nights:
        cells = (f'<td>{esc(nrec.date or nrec.label)}</td><td>{nrec.total}</td>'
                 + "".join(f'<td>{nrec.verdicts.get(v, 0)}</td>' for v in VERDICT_ORDER)
                 + f'<td>{nrec.false_done}</td><td>{nrec.interventions}</td>'
                 + f'<td>{esc(nrec.green_over_eligible or "-")}</td>')
        rows.append(f'<tr>{cells}</tr>')
    return (
        '<details class="tableview"><summary>Table view (accessibility / exact numbers)</summary>'
        '<div class="scrollx"><table class="data"><thead>' + head + '</thead><tbody>'
        + "".join(rows) + '</tbody></table></div></details>'
    )


def _verdict_trend_card(nights: list[NightRecord]) -> str:
    return (
        '<div class="chart-card"><h3>Verdict mix, night over night</h3>'
        '<p class="cap">Every job lands one of four honest verdicts (plus RECOVERED). GREEN is the '
        'only banked "done"; PARKED-HONEST is a valid run that fell short and still banks; STALLED is '
        'an invalid run; FALSE-DONE is a claimed-done that wasn’t (must stay 0).</p>'
        + _verdict_legend()
        + _svg_verdict_bars(nights)
        + _night_table(nights)
        + '</div>'
    )


def _guest_agreement_card(nights: list[NightRecord]) -> str:
    latest = nights[-1] if nights else None
    if latest is None:
        return ""
    tot = {k: sum(nrec.guest_agreement.get(k, 0) for nrec in nights) for k in GUEST_AGREEMENT_ORDER}
    rows = "".join(
        f'<tr><td>{esc(k)}</td><td>{tot[k]}</td></tr>' for k in GUEST_AGREEMENT_ORDER
    )
    return (
        '<div class="chart-card"><h3>Guest-oracle agreement (#744, advisory)</h3>'
        '<p class="cap">The NIC-less Alpine guest re-runs the oracle for substrate-independent '
        'corroboration. <strong>agree/DIVERGENCE</strong> is the datum; the certificate is evidence, '
        'never a gate. DIVERGENCE &gt; 0 warrants a look. (Totals across all measured nights.)</p>'
        '<div class="scrollx"><table class="data"><thead><tr><th>Agreement</th><th>Count</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div></div>'
    )


def _advisory_empty(title: str, tickets: str, what: str, when: str, *, pill: str = "advisory") -> str:
    """Empty-state card for a not-yet-populated trend block. ``pill`` labels the block's
    authority honestly: 'advisory' for #827/#837 (never changes a verdict), 'integrity' for
    #832 (the ONE sanctioned VERDICT-CHANGING extension — never call it advisory), or ''
    for a disclosure block (#821/#826 coverage) that only annotates a GREEN."""
    if pill == "advisory":
        badge = '<span class="pill advisory">ADVISORY</span>'
    elif pill == "integrity":
        badge = '<span class="pill live">INTEGRITY · verdict-changing</span>'
    elif pill:
        badge = f'<span class="pill planned">{esc(pill.upper())}</span>'
    else:
        badge = ""
    return (
        f'<div class="chart-card"><h3>{esc(title)} {badge}</h3>'
        f'<p class="cap">{esc(what)}</p>'
        '<div class="empty-state"><span class="h">No data yet.</span>'
        f'None of the accumulated battery summaries carry the <code>{esc(tickets)}</code> block. '
        f'{esc(when)} This is an honest empty state &mdash; the trend is not fabricated before the '
        'instrument runs.</div></div>'
    )


def _failure_taxonomy_card(nights: list[NightRecord]) -> str:
    tnights = [n for n in nights if n.has_taxonomy]
    if not tnights:
        return _advisory_empty(
            "Failure-class trend (#827)",
            "failure_taxonomy",
            "Deterministic failure classes at battery close (ORACLE-DEFECT, INTEGRATION-SEAM, "
            "BLIND-FIX-LOOP, DECOMPOSE-DOWNGRADE, HARNESS-BUDGET, UNCLASSIFIED). Its UNCLASSIFIED "
            "rate is the instrument’s own health metric — a rising share means a new leak "
            "class. oracle-defect / seam / blind park counts read straight off this block.",
            "The first datapoint lands after a battery run with the #827 classifier wired at "
            "battery close.",
        )
    # Real render: per-class table across taxonomy nights.
    head = '<tr><th>Night</th>' + "".join(f'<th>{esc(c)}</th>' for c in FAILURE_CLASS_ORDER) + '<th>UNCLASS. rate</th></tr>'
    rows = []
    for nrec in tnights:
        cells = (f'<td>{esc(nrec.date or nrec.label)}</td>'
                 + "".join(f'<td>{nrec.failure_classes.get(c, 0)}</td>' for c in FAILURE_CLASS_ORDER)
                 + f'<td>{esc(nrec.unclassified_rate or "-")}</td>')
        rows.append(f'<tr>{cells}</tr>')
    return (
        '<div class="chart-card"><h3>Failure-class trend (#827) '
        '<span class="pill advisory">ADVISORY</span></h3>'
        '<p class="cap">Deterministic classification at battery close; never changes a verdict. '
        'oracle-defect / seam / blind park counts read off these columns.</p>'
        '<div class="scrollx"><table class="data"><thead>' + head + '</thead><tbody>'
        + "".join(rows) + '</tbody></table></div></div>'
    )


def _green_quality_card(nights: list[NightRecord]) -> str:
    qn = [n for n in nights if n.has_green_quality]
    if not qn:
        return _advisory_empty(
            "GREEN-quality bands (#837)",
            "green_quality",
            "A/B/C GREEN-quality bands (leniency drift) computed by a deterministic formula over "
            "the Layer-1 archetype-regression floor + craft lints (advisory jury optional). A = clean, "
            "B = caveats, C = concerning (a behavior regression vs the last archived GREEN). Advisory "
            "forever — a band never changes a verdict.",
            "The first datapoint lands after a battery run with the #837 GREEN-quality audit wired "
            "at battery close.",
        )
    head = '<tr><th>Night</th>' + "".join(f'<th>Band {esc(b)}</th>' for b in BAND_ORDER) + '<th>Regressed</th><th>Craft residue</th><th>Mode</th></tr>'
    rows = []
    for nrec in qn:
        cells = (f'<td>{esc(nrec.date or nrec.label)}</td>'
                 + "".join(f'<td>{nrec.quality_bands.get(b, 0)}</td>' for b in BAND_ORDER)
                 + f'<td>{nrec.quality_regressed}</td><td>{nrec.quality_craft_residue}</td>'
                 + f'<td>{esc(nrec.quality_mode or "-")}</td>')
        rows.append(f'<tr>{cells}</tr>')
    return (
        '<div class="chart-card"><h3>GREEN-quality bands (#837) '
        '<span class="pill advisory">ADVISORY</span></h3>'
        '<p class="cap">Advisory band only; never gates a verdict.</p>'
        '<div class="scrollx"><table class="data"><thead>' + head + '</thead><tbody>'
        + "".join(rows) + '</tbody></table></div></div>'
    )


def _green_integrity_card(nights: list[NightRecord]) -> str:
    gn = [n for n in nights if n.has_green_integrity]
    if not gn:
        return _advisory_empty(
            "Earned-GREEN integrity downgrades (#832)",
            "green_integrity",
            "The one sanctioned verdict-authority extension: a deterministic grader-tampering "
            "fingerprint downgrades a GREEN to PARKED-HONEST, counted here by fingerprint class. "
            "0 downgrades is the healthy state. This is INTEGRITY, not advisory — it is the only "
            "signal permitted to move a verdict (ADR-037 §1 inv.6).",
            "The block appears in every summary the current battery writes; historical summaries "
            "predate it, so it reads as no-data until the next run.",
            pill="integrity",
        )
    rows = []
    for nrec in gn:
        classes = ", ".join(f"{k}:{v}" for k, v in sorted(nrec.integrity_class_counts.items()) if v) or "none"
        rows.append(f'<tr><td>{esc(nrec.date or nrec.label)}</td><td>{nrec.integrity_downgraded}</td>'
                    f'<td>{esc(classes)}</td></tr>')
    return (
        '<div class="chart-card"><h3>Earned-GREEN integrity downgrades (#832)</h3>'
        '<p class="cap">Deterministic tampering-fingerprint scan; a match downgrades GREEN&rarr;PARKED, '
        'quoting file:line. 0 is healthy.</p>'
        '<div class="scrollx"><table class="data"><thead><tr><th>Night</th><th>Downgraded</th>'
        '<th>By class</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div></div>'
    )


def _oracle_coverage_card(nights: list[NightRecord]) -> str:
    cov_nights = [(n, n.oracle_coverage()) for n in nights if n.oracle_coverage() is not None]
    if not cov_nights:
        return _advisory_empty(
            "Oracle coverage % over GREENs (#821/#826)",
            "failure_taxonomy.green_classes",
            "The share of banked GREENs that are FULLY verified (k/n test-tier criteria covered). "
            "A GREEN names its coverage (ADR-037 §6): partial-coverage GREENs are disclosed, "
            "never rubber-stamped. Derived from #827’s green-class stamp, which reads #821’s "
            "oracle_coverage k/n.",
            "The first datapoint lands once #821 stamps oracle_coverage and #827 classifies it at "
            "battery close.",
            pill="disclosure",
        )
    rows = []
    for nrec, cov in cov_nights:
        k, ncov = cov
        pct = f"{(100 * k / ncov):.0f}%" if ncov else "n/a"
        rows.append(f'<tr><td>{esc(nrec.date or nrec.label)}</td><td>{k}/{ncov}</td><td>{esc(pct)}</td></tr>')
    return (
        '<div class="chart-card"><h3>Oracle coverage % over GREENs (#821/#826)</h3>'
        '<p class="cap">Fully-verified GREENs (k) over classified GREENs (n).</p>'
        '<div class="scrollx"><table class="data"><thead><tr><th>Night</th><th>k/n</th><th>%</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div></div>'
    )


def _section_b(nights: list[NightRecord], summ: HistorySummary) -> str:
    if not nights:
        body = ('<div class="empty-state"><span class="h">No battery history yet.</span>'
                'The first datapoint lands after tonight’s battery run writes a '
                '<code>battery-summary.json</code>. Section B renders trends as history accumulates.</div>')
    else:
        body = (
            _headline_tiles(summ)
            + _verdict_trend_card(nights)
            + _failure_taxonomy_card(nights)
            + _oracle_coverage_card(nights)
            + _green_quality_card(nights)
            + _green_integrity_card(nights)
            + _guest_agreement_card(nights)
        )
    return (
        '<h2 class="section">Section B &mdash; Grading Health '
        '<span class="tag">night-over-night trends from the battery-summary history</span></h2>'
        '<p class="lead">The nightly M2 capability battery writes a <code>battery-summary/v1</code> '
        'record. These trends read that accumulating history: the FALSE-DONE=0 / interventions=0 honesty '
        'invariants, the verdict mix, and the advisory #827/#832/#837 grading-health blocks (rendered '
        'with an honest empty state until each classifier is wired at battery close).</p>'
        + body
    )


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

def render_html(
    demo_results: list[DemoResult],
    nights: list[NightRecord],
    summ: HistorySummary,
    *,
    generated_at: str = "",
    battery_dir: str = "",
) -> str:
    asof = generated_at or (f"as of {summ.latest_date}" if summ.latest_date else "no battery data yet")
    raw = {
        "generated_at": asof,
        "battery_dir": battery_dir,
        "section_a": [r.to_dict() for r in demo_results],
        "section_b": [n.to_dict() for n in nights],
    }
    data_blob = json.dumps(raw, indent=2, ensure_ascii=False)

    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>BlarAI — Grading &amp; Integration Machinery: Live Proof</title>\n"
        f"<link rel=\"icon\" href=\"{_favicon()}\">\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        "<div id=\"tooltip\"></div>\n"
        "<div class=\"wrap\">\n"
        "<header class=\"top\">\n"
        "<div>"
        "<h1>Grading &amp; Integration Machinery &mdash; Live Proof</h1>"
        "<p class=\"sub\">One re-generatable dashboard that proves the ADR-037 grading machinery works "
        "&mdash; a Proof section of Tier-1 gate demos and a Grading-Health section of night-over-night "
        "trends. Honesty is this deliverable’s own subject: every claim maps to a real observable, "
        "and anything dormant, advisory, or not-yet-wired is labeled as such.</p>"
        f"<div class=\"asof\">{esc(asof)} &middot; regenerate with "
        "<code>scripts/live_proof/generate_dashboard.py</code></div>"
        "</div>\n"
        "<button id=\"theme-toggle\" class=\"theme-toggle\">Toggle theme</button>\n"
        "</header>\n"
        "<div class=\"banner\">"
        "<strong>Reading this dashboard:</strong> a <span class=\"pill live\">BUILD: LIVE</span> pill "
        "means the gate exists in the codebase; a <span class=\"pill stub\">DEMO: STUB</span> pill means "
        "its worked demo is scaffolding not yet wired to a live run &mdash; no evidence is fabricated for "
        "a stub. <span class=\"pill advisory\">ADVISORY</span> marks a signal that never changes a "
        "verdict.</div>\n"
        + _section_a(demo_results)
        + _section_b(nights, summ)
        + "<footer class=\"foot\">\n"
        "<div class=\"legendkey\"><strong>Real vs stubbed.</strong> Section A demo drivers are all STUBs "
        "at this scaffold (the abstraction + registry are built; real drivers land per ticket). Section B "
        "reads REAL <code>battery-summary/v1</code> history for verdicts / FALSE-DONE / interventions / "
        "guest-agreement; the #827 / #832 / #837 blocks show an honest empty state until those classifiers "
        "run at battery close.</div>\n"
        "<div>Regenerate: <code>python scripts/live_proof/generate_dashboard.py --open</code> &middot; "
        "self-contained (no network) &middot; theme-aware (system + toggle).</div>\n"
        "<details class=\"tableview\"><summary>Raw data (JSON this page rendered from)</summary>"
        f"<div class=\"evidence\">{esc(data_blob)}</div></details>\n"
        "</footer>\n"
        "</div>\n"
        f"<script>{_JS}</script>\n"
        "</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_evidence(path: str | None) -> dict:
    """Optional Section-A evidence data JSON: ``{"section_a": {"<gate_key>": {...}}}``. Absent
    or malformed -> {} (every demo then renders as its registry STUB)."""
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    ev = data.get("section_a") if isinstance(data, dict) else None
    return ev if isinstance(ev, dict) else {}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="generate_dashboard.py",
        description="Generate the #840 grading-&-integration live-proof dashboard (self-contained HTML).",
    )
    p.add_argument("--battery-dir", metavar="DIR",
                   help="Battery state root (default: C:/Users/mrbla/agentic-setup/state/battery).")
    p.add_argument("--evidence", metavar="FILE",
                   help="Optional Section-A evidence data JSON (real gate-run excerpts once drivers wire in).")
    p.add_argument("--out", metavar="FILE", help=f"Output HTML path (default: {DEFAULT_OUT}).")
    p.add_argument("--generated-at", metavar="STAMP",
                   help="Override the 'as of' stamp (for reproducible bytes). Default: latest night date.")
    p.add_argument("--include-dry-run", action="store_true",
                   help="Include dry-run summaries in Section B (default: excluded).")
    p.add_argument("--open", action="store_true", help="Open the generated dashboard in the default browser.")
    args = p.parse_args(argv)

    battery_dir = Path(args.battery_dir) if args.battery_dir else None
    nights = read_history(battery_dir, include_dry_run=args.include_dry_run)
    summ = summarize(nights)
    evidence_by_gate = _load_evidence(args.evidence)
    demo_results = collect_demo_results(evidence_by_gate=evidence_by_gate)

    html = render_html(
        demo_results, nights, summ,
        generated_at=args.generated_at or "",
        battery_dir=str(battery_dir) if battery_dir else "C:/Users/mrbla/agentic-setup/state/battery",
    )
    out = Path(args.out) if args.out else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"live-proof dashboard written: {out}")
    print(f"  Section A: {len(demo_results)} gate demos "
          f"({sum(1 for r in demo_results if r.wired)} wired, "
          f"{sum(1 for r in demo_results if not r.wired)} stubbed)")
    print(f"  Section B: {len(nights)} measured night(s)"
          + (f", latest {summ.latest_date}" if summ.latest_date else " (no history yet)"))

    if args.open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
