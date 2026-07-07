#!/usr/bin/env python
"""One-command test battery for the lessons deck.

    python run_checks.py [--shots sample|all] [--skip-headless]

Steps (each gates the exit code unless marked otherwise):
  1. validate  — validate_acts.py: schema, act rosters, vocabulary allowlist,
                 anti-hallucination (every cited entry + SHA on disk),
                 diagram/stat lint, core-path cross-check
  2. build     — build_lessons_deck.py renders lessons_deck.html
  3. parse     — verify_deck_html.mjs: every diagram string EMBEDDED in the
                 HTML parses under real mermaid (Node; skips with a warning
                 if Node is unavailable — the headless audit still covers it)
  4. audit     — headless Edge/Chrome loads the deck with ?audit=1: every
                 slide is activated and measured — diagram render errors,
                 PAINT spills (SVG ink past its card — the bug class layout
                 numbers alone cannot see), horizontal overflow. Writes
                 _audit_report.json.
  5. selftest  — headless ?selftest=1: navigation, unit jumps, mark-studied,
                 core/full mode filtering, index, rail, resume.
  6. shots     — optional screenshot sweep at presentation size (1440x810)
                 into _shots/ : "sample" = title/guide/index + every act
                 intro + EVERY mechanism (diagram) slide + the first unit;
                 "all" = every slide (slow, ~1.5 s each).

The headless steps use a throwaway browser profile and the deck's separate
test localStorage key — real study progress is never touched.
"""
import html as html_mod
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

# Windows consoles default to a legacy codepage; the validator/build output
# carries em-dashes and arrows. Never let a print() kill the battery.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

D = pathlib.Path(__file__).resolve().parent
DECK = D / "lessons_deck.html"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def browser():
    for b in BROWSERS:
        if pathlib.Path(b).exists():
            return b
    return None


def s_validate() -> bool:
    r = run([sys.executable, str(D / "validate_acts.py")])
    print(r.stdout[-3000:])
    return r.returncode == 0


def s_build() -> bool:
    r = run([sys.executable, str(D / "build_lessons_deck.py")])
    print(r.stdout, r.stderr[-1500:] if r.returncode else "")
    return r.returncode == 0


def s_node_parse() -> bool:
    node = shutil.which("node")
    if not node:
        print("node not found — SKIP (headless audit still renders every diagram)")
        return True
    r = run([node, str(D / "verify_deck_html.mjs")])
    print(r.stdout[-2500:])
    if r.returncode:
        print(r.stderr[-800:])
    return r.returncode == 0


def headless(mode: str):
    b = browser()
    if not b:
        print("no Edge/Chrome found for the headless steps")
        return None
    uri = DECK.as_uri() + f"?{mode}=1"
    r = run([b, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
             "--window-size=1440,810", "--virtual-time-budget=60000", "--dump-dom", uri],
            timeout=240)
    m = re.search(r'<pre id="auditout">(.*?)</pre>', r.stdout, re.S)
    if not m or not m.group(1).strip():
        print(f"{mode}: no report captured (stdout {len(r.stdout)} bytes)")
        print(r.stderr[-600:])
        return None
    try:
        return json.loads(html_mod.unescape(m.group(1)))
    except Exception as e:  # noqa: BLE001
        print(f"{mode}: report unparseable: {e}")
        return None


def s_audit() -> bool:
    rep = headless("audit")
    if rep is None:
        return False
    (D / "_audit_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: rep.get(k) for k in
                      ("slides", "units", "diagrams", "rendered_svgs", "summary", "pass")}, indent=1))
    for k in ("mmd_errors", "paint_spills", "h_overflow"):
        if rep.get(k):
            print(f"  {k}: {rep[k][:12]}")
    if rep.get("extreme_v_overflow"):
        print(f"  note (non-gating): tall slides at {rep['extreme_v_overflow'][:12]}")
    if rep.get("shrunk"):
        print(f"  note (non-gating): {len(rep['shrunk'])} diagrams scaled <0.55, "
              f"first: {rep['shrunk'][:10]}")
    return bool(rep.get("pass"))


def s_selftest() -> bool:
    rep = headless("selftest")
    if rep is None:
        return False
    print(json.dumps(rep, indent=1)[:1200])
    return bool(rep.get("pass"))


def slide_types():
    text = DECK.read_text(encoding="utf-8")
    return re.findall(r'<section class="slide" data-type="([a-z-]+)"', text)


def sample_targets(types):
    n = len(types)
    sections = [k + 1 for k, t in enumerate(types) if t == "section"]
    mech = [k + 1 for k, t in enumerate(types) if t == "lesson-mech"]
    first_unit = [sections[0] + 1, sections[0] + 2, sections[0] + 3] if sections else []
    return sorted({t for t in [1, 2, 3, 4] + sections + first_unit + mech if 1 <= t <= n})


def s_shots(which: str) -> bool:
    b = browser()
    if not b:
        print("no browser for screenshots")
        return False
    types = slide_types()
    targets = list(range(1, len(types) + 1)) if which == "all" else sample_targets(types)
    shots = D / "_shots"
    shots.mkdir(exist_ok=True)
    t0 = time.time()
    for j, n in enumerate(targets, 1):
        out = shots / f"slide{n:03d}.png"
        run([b, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
             f"--screenshot={out}", "--window-size=1440,810", "--virtual-time-budget=30000",
             DECK.as_uri() + f"#{n}"], timeout=120)
        if j % 25 == 0:
            print(f"  {j}/{len(targets)} shots ({time.time() - t0:.0f}s)", flush=True)
    done = sum(1 for n in targets if (shots / f"slide{n:03d}.png").exists())
    print(f"{done}/{len(targets)} screenshots -> {shots}")
    return done == len(targets)


def main() -> int:
    shots = None
    skip_headless = "--skip-headless" in sys.argv
    if "--shots" in sys.argv:
        k = sys.argv.index("--shots")
        shots = sys.argv[k + 1] if k + 1 < len(sys.argv) else "sample"
    steps = [("validate", s_validate), ("build", s_build), ("diagram-parse", s_node_parse)]
    if not skip_headless:
        steps += [("headless-audit", s_audit), ("headless-selftest", s_selftest)]
    if shots:
        steps += [("screenshots", lambda: s_shots(shots))]
    results = {}
    for name, fn in steps:
        print(f"\n=== {name} ===", flush=True)
        t0 = time.time()
        try:
            ok = fn()
        except Exception as e:  # noqa: BLE001
            print(f"step crashed: {e}")
            ok = False
        results[name] = ok
        print(f"--- {name}: {'PASS' if ok else 'FAIL'} ({time.time() - t0:.1f}s)", flush=True)
        if not ok and name in ("validate", "build"):
            break  # later steps need the artifact
    print("\n==== SUMMARY ====")
    for k, v in results.items():
        print(f"  {k:18} {'PASS' if v else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
