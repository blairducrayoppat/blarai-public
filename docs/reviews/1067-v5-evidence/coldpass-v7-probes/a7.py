"""A7: harvest every probe string from the v5 and v6 cold-pass probe corpora and
re-run them against v7, with the echo prefix normalised so the ECHO layer can
never be the thing that answers."""
import sys, ast, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad/v7cold/mainmod")
from shared.coordinator import prose_guard as pg
import main_guard as mg

EV = pathlib.Path(r"C:/Users/mrbla/wt-1067-v7/docs/reviews/1067-v5-evidence")
NAMES = ("bill-splitter", "acceptance-tests", "parser", "runner", "packager",
         "migration", "command-interface", "auth", "api", "ui")

FAILED = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
M_FAILED = mg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)


def harvest(d):
    out = []
    for f in sorted(d.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                s = n.value.strip()
                if len(s) > 12 and " " in s and not s.startswith(("=== ", "  ", "#")) \
                        and "sys.path" not in s and "%s" not in s and "\n" not in s:
                    out.append(s)
    return out


def strip_prefix(s):
    for tok in ("INCOMPLETE:", "PARKED:", "SUCCEEDED:"):
        if s.upper().startswith(tok):
            return s[len(tok):].strip()
    return s


for name in ("coldpass-v5-probes", "coldpass-v6-probes"):
    probes = sorted(set(harvest(EV / name)))
    print(f"\n### {name}: {len(probes)} harvested probe strings ###")
    v7_only, both_ok, echo = [], [], 0
    for p in probes:
        body = strip_prefix(p)
        text = "INCOMPLETE: " + body
        d = pg.ProseGuard().validate_run_summary(FAILED, text, task_names=NAMES)
        if d.action == "rejected:echo-missing" or d.action.startswith("rejected:echo-mismatch"):
            echo += 1
            continue
        m = mg.ProseGuard().validate_run_summary(M_FAILED, text)
        if d.accepted and not m.accepted:
            v7_only.append((body, d.action))
        elif d.accepted:
            both_ok.append(body)
    print(f"  answered by ECHO layer: {echo} (excluded)")
    print(f"  v7 ACCEPT / main REFUSE  = {len(v7_only)}")
    for b, a in v7_only:
        print(f"    [V7-ONLY] {b!r}")
    print(f"  accepted by BOTH (pre-existing, no claim match) = {len(both_ok)}")
    for b in both_ok[:40]:
        print(f"    (main-too) {b!r}")
