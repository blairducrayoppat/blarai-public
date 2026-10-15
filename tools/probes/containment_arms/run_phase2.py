"""Run the #1740 phase-2 matrix: every setup on the same payload, every lock with a control and a lock-off run.

Stages (each can be run alone):
  prep          create the throwaway fixtures and the fixture copy of the toolchain
  controls      arm D on the fixture toolchain (n=5): the control for every later arm, and run-to-run variation
  b             B1, B2, B2 with a fence naming the synthetic SID, B3 on the fixture toolchain; B3 on the real
                toolchain (n=3 each)
  c             arm C variants: no capabilities / loopback exemption / internetClient / internetClient + a fence
                naming the package; and C on the real toolchain (n=3 each)
  discriminate  the app-scoped separation test: D, B2, B3 under a block alone (positive control) and under a
                block with an operator permit; a visible countdown with a STOP button comes first
  teardown      remove the fixtures and verify nothing was left behind
  verify-clean  read-only check that no fence objects, loopback exemptions or AppContainer profiles remain

Run elevated:  python -I run_phase2.py --stage <name> --out <raw-data dir> [--runs N]
Every stage records what it ran and each launch's exit code in <out>/stage-<name>.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = "C:/Python314/python.exe"
PWSH = "C:/Program Files/PowerShell/7/pwsh.exe"
CREATE_NO_WINDOW = 0x08000000
FIXTURE_ROOT = Path("C:/blarai-spike-1740")

# (name, arm, extra run_arm arguments)
CONTROLS = [("D-fixture", "D", ["--toolchain", "fixture"])]
B_STAGE = [
    ("B1-fixture", "B1", ["--toolchain", "fixture"]),
    ("B2-fixture", "B2", ["--toolchain", "fixture"]),
    ("B2-fixture-fence-synthetic-sid", "B2", ["--toolchain", "fixture", "--fence", "user:write-sid"]),
    ("B3-fixture", "B3", ["--toolchain", "fixture"]),
    ("B3-real-toolchain", "B3", []),
]
C_STAGE = [
    ("C-real-toolchain", "C", []),
    ("C0-fixture-no-capabilities", "C", ["--toolchain", "fixture"]),
    ("C1-fixture-loopback-exempt", "C", ["--toolchain", "fixture", "--loopback-exempt"]),
    ("C2-fixture-internetClient", "C", ["--toolchain", "fixture", "--capabilities", "internetClient"]),
    ("C3-fixture-internetClient-fence-package", "C",
     ["--toolchain", "fixture", "--capabilities", "internetClient", "--loopback-exempt", "--fence", "package:auto"]),
]
DISCRIMINATE = [
    (f"{arm}-fixture-{variant}", arm, ["--toolchain", "fixture", "--fence", f"discriminate:{variant}"])
    for variant in ("block-only", "block-permit") for arm in ("D", "B2", "B3")
]
COUNTDOWN_MESSAGE = (
    "In two minutes BlarAI will run a short network test (about two minutes long). It is built to affect one test "
    "program only (python.exe inside C:\\blarai-spike-1740); your own browsing and tools should not be touched, and "
    "an automatic cutoff removes the test rules if your internet stops. Press STOP to cancel it."
)


def hidden(argv: list[str], timeout: float = 1800) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, check=False)


def run_variants(variants: list[tuple[str, str, list[str]]], out: Path, runs: int,
                 label: str) -> list[dict[str, object]]:
    records = []
    for name, arm, extra in variants:
        dest = out / f"arm-{name}"
        argv = [PY, "-I", str(HERE / "run_arm.py"), "--arm", arm, "--runs", str(runs), "--phase2",
                "--out", str(dest), "--label", name, *extra]
        started = datetime.now().astimezone().isoformat(timespec="seconds")
        cp = hidden(argv)
        records.append({"variant": name, "arm": arm, "argv": argv, "started": started,
                        "rc": cp.returncode, "stdout_tail": cp.stdout.strip().splitlines()[-6:],
                        "stderr_tail": cp.stderr.strip().splitlines()[-6:]})
        print(name, "rc", cp.returncode, flush=True)
    return records


def verify_clean() -> dict[str, object]:
    """Read-only: no fence objects, no loopback exemption for our package, no profile folder."""
    fence = hidden([PWSH, "-NoProfile", "-File", str(HERE / "wfp_fence.ps1"), "-DryRun"])
    exempt = hidden(["C:/Windows/System32/CheckNetIsolation.exe", "LoopbackExempt", "-s"])
    profile = Path.home() / "AppData/Local/Packages/blarai.1740.coder"
    state = json.loads(fence.stdout.split("DRY RUN")[0].strip()) if "sublayer" in fence.stdout else {}
    return {
        "fence_state": state,
        "fence_clean": bool(state) and not state.get("sublayer") and not state.get("provider") and not state.get("filters"),
        "loopback_exemption_present": "blarai.1740" in exempt.stdout.lower(),
        "appcontainer_profile_folder_present": profile.exists(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", required=True,
                    choices=["prep", "controls", "b", "c", "discriminate", "teardown", "verify-clean"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--countdown-seconds", type=int, default=120)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {"stage": args.stage, "runs_per_variant": args.runs,
                                 "started": datetime.now().astimezone().isoformat(timespec="seconds")}
    rc = 0
    if args.stage == "prep":
        steps = [hidden([PY, "-I", str(HERE / "fixtures.py")]),
                 hidden([PY, "-I", str(HERE / "fixtures.py"), "--toolchain-copy"])]
        result["steps"] = [{"rc": s.returncode, "stdout_tail": s.stdout.strip().splitlines()[-12:],
                            "stderr_tail": s.stderr.strip().splitlines()[-4:]} for s in steps]
        rc = max(s.returncode for s in steps)
    elif args.stage == "controls":
        result["variants"] = run_variants(CONTROLS, args.out, max(args.runs, 5), "controls")
    elif args.stage == "b":
        result["variants"] = run_variants(B_STAGE, args.out, args.runs, "b")
    elif args.stage == "c":
        result["variants"] = run_variants(C_STAGE, args.out, args.runs, "c")
    elif args.stage == "discriminate":
        gate = hidden([PWSH, "-NoProfile", "-File", str(HERE / "countdown_gate.ps1"), "-Seconds",
                       str(args.countdown_seconds), "-Title", "BlarAI network test starts soon",
                       "-Message", COUNTDOWN_MESSAGE], timeout=args.countdown_seconds + 120)
        result["countdown_exit"] = gate.returncode
        if gate.returncode != 0:
            result["aborted"] = "countdown stopped or could not be shown; nothing was run"
            rc = 1
        else:
            result["variants"] = run_variants(DISCRIMINATE, args.out, args.runs, "discriminate")
    elif args.stage == "teardown":
        cp = hidden([PY, "-I", str(HERE / "fixtures.py"), "--teardown"])
        result["teardown"] = {"rc": cp.returncode, "stdout": cp.stdout.strip(), "stderr_tail": cp.stderr.strip().splitlines()[-3:]}
        result["fixtures_gone"] = not FIXTURE_ROOT.exists()
        rc = cp.returncode
    elif args.stage == "verify-clean":
        result["state"] = verify_clean()
        state = result["state"]
        rc = 0 if (state["fence_clean"] and not state["loopback_exemption_present"]
                   and not state["appcontainer_profile_folder_present"]) else 1
    result["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
    result["rc"] = rc
    (args.out / f"stage-{args.stage}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("variants", "steps")}, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
