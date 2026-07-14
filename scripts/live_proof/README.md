# Live-Proof Dashboard (`scripts/live_proof/`) — Vikunja #840

A single, re-generatable, self-contained HTML dashboard that proves the ADR-037
**grading & integration machinery** works. It has two sections and a cockpit entry point.

> **Honesty is this deliverable's own subject.** Every claim maps to a real observable.
> Anything dormant, advisory, or not-yet-wired is **labeled as such**, and nothing is ever
> fabricated. That discipline is the point of the dashboard, so it is the point of this code.

This directory is **SCAFFOLD** (#840 c.1782): the abstractions, the registry, the Section-B
reader, and the generator are built; the Section-A *demo drivers* are stubs that the real
gate-run drivers replace later. See **[What is real vs stubbed](#what-is-real-vs-stubbed)**.

---

## Regenerate

```bash
python scripts/live_proof/generate_dashboard.py --open
```

Writes `scripts/live_proof/grading_health_dashboard.html` (a build artifact — not committed)
and opens it in the default browser. Common flags:

| Flag | Meaning |
|------|---------|
| `--battery-dir DIR` | Battery state root. Default `C:/Users/mrbla/agentic-setup/state/battery`. |
| `--evidence FILE`   | Optional Section-A evidence JSON (real gate-run excerpts, once drivers wire in). |
| `--out FILE`        | Output HTML path. |
| `--generated-at STAMP` | Override the "as of" stamp (for reproducible bytes). Default: latest night's date. |
| `--include-dry-run` | Include dry-run battery summaries in Section B (default: excluded). |
| `--open`            | Open the result in the default browser. |

The generator is **deterministic** (same inputs → byte-identical output) and does **no
network** and no writes outside `--out`.

### Cockpit entry point

`agentic-setup/scripts/control-panel.ps1` carries a `[Q] Quality & Grading Health` menu item
that regenerates this dashboard and opens it. That file lives in the *other* repo
(`agentic-setup`); the snippet to add it is in the #840 builder report, not applied from here.

---

## What the dashboard shows

### Section A — "Proof" (Tier-1 acceptance demos)

One card per gate in the ADR-037 ladder. Each card names what the gate **proves** and
**cannot prove**, then shows the worked demo as `input → machinery response → target
verdict`, plus a real evidence excerpt **once the driver is wired**. Two independent status
pills keep the honesty layer explicit:

* **BUILD: LIVE / STAGED / PLANNED** — the gate's presence in the codebase (from ADR-037's
  PLANNED-vs-BUILT split). A LIVE gate really exists in `tools/dispatch_harness` / `shared/fleet`.
* **DEMO: STUB / CAUGHT / PASS** — whether *the demo itself* is wired to a live gate run. At
  scaffold time every demo is a **STUB** — no evidence produced, nothing fabricated. A LIVE
  gate can still have a STUB demo; the dashboard never renders a stub as a pass.

The 10 gates registered (ladder order): static pre-gate #831 · import-contract / clean-env
grading #822 · console channel #823 · exec-smoke #830 · oracle-QA #821 · mutation #828 ·
flake differential #829 · decompose recovery #824 · tampering scan #832 · GREEN-audit #837.

### Section B — "Grading Health" (trends)

Night-over-night trends read from the accumulating `battery-summary.json` history
(`battery-summary/v1`, written by `tools/dispatch_harness/battery.py`):

* **Honesty invariants** — FALSE-DONE and interventions per night (target 0; a per-night dot
  strip makes any breach obvious), plus the GREEN-over-plan-graph-eligible honest rate (#789).
* **Verdict mix** — a stacked bar per night (GREEN / PARKED-HONEST / RECOVERED / STALLED /
  FALSE-DONE) with a table view for exact numbers.
* **Guest-oracle agreement** (#744, advisory) — agree / DIVERGENCE / not-run / no-certificate.
* **Advisory & disclosure blocks** — the failure-class trend (#827), the oracle-coverage %
  disclosure (#821/#826), the GREEN-quality bands (#837), and the earned-GREEN **integrity**
  downgrades (#832). Each is labeled by its true authority: *advisory* (#827/#837 never change
  a verdict), *disclosure* (#821/#826 annotate a GREEN's coverage), or *integrity ·
  verdict-changing* (#832 — the one sanctioned downgrade, ADR-037 §1 inv.6).

---

## What is real vs stubbed

| Piece | State |
|-------|-------|
| `demo_registry.py` — driver abstraction + 10-gate registry | **Real** scaffold. Every driver is a `StubDemoDriver`. |
| Section-A demo evidence (CAUGHT/PASS + excerpts) | **Stubbed.** No evidence produced; real drivers land per ticket. |
| `battery_reader.py` — `battery-summary/v1` history ingest | **Real & working** against the live history. |
| Section-B verdict / FALSE-DONE / interventions / guest-agreement trends | **Real data.** |
| Section-B #827 / #832 / #837 / oracle-coverage blocks | **Real reader; no data yet** — historical summaries predate the classifiers, so these render an honest empty state until a battery run writes them. |
| `generate_dashboard.py` — self-contained, theme-aware HTML renderer | **Real & working.** |

### Wiring a real Section-A demo

Subclass `DemoDriver` in `demo_registry.py`, implement `run(evidence)` against an actual gate
run, and return a `DemoResult` with `wired=True`, `status=DEMO_CAUGHT`/`DEMO_PASS`, a real
`evidence_excerpt`, and its `evidence_source`. Replace that gate's entry in `build_registry()`.
The generator renders wired demos with their evidence and stubs as scaffold placeholders — no
code change needed in the generator.

## Files

* `generate_dashboard.py` — the generator (CLI + HTML renderer). Deterministic, no network.
* `demo_registry.py` — Section A: the demo-driver abstraction + the 10-gate stub registry.
* `battery_reader.py` — Section B: the `battery-summary/v1` history reader + roll-up.
* `README.md` — this file.

## Design notes

Self-contained (all CSS/JS inline, favicon as an inline SVG data URI, no external requests);
theme-aware (`prefers-color-scheme` + a `data-theme` toggle that persists in `localStorage`);
responsive; wide tables/charts scroll inside their own container. Chart colors use the dataviz
reference categorical + status palette, validated for light and dark; every verdict mark ships
with a label and count, so a status color never carries meaning alone.
