# NOTE (2026-10-11 review): these probes were built for one finished study on a dev box and are not hardened for reuse.
# The throwaway roots inherit write access from C:\ for other accounts and the fixture tree is owned by the operator;
# before reusing any of it, restrict the roots to administrators and SYSTEM and take ownership away from the operator.
"""Arm E of #1740: run the probe payload inside a Microsoft MXC container (tier 1, the operating system's own container).

Safety design (each check is recorded in every run record):
  * The launcher is Microsoft-signed and its SHA-256 equals the published release digest (checked before every batch).
  * `wxc-exec --probe` must report tier "base-container" with no ACL augmentation, or nothing runs.
  * Every config sets fallback.allowDaclMutation=false and is validated with --dry-run first.
  * Only throwaway folders are granted (the fixture toolchain copy, the payload, the work folder).
  * MXC's crash-recovery state directory is redirected to a throwaway folder.
  * Before and after every run: the access lists of the granted folders, the registry mapping key MXC writes,
    the AppContainer profile list and MXC's state folder are compared; any difference is recorded and stops the batch.

Run elevated after `run_phase2.py --stage prep`:
  python -I run_arm_e.py --out <raw-data dir> [--runs 3] [--variants E0,E1,E2,E3,E4]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_arm
import winsec as w

MXC_ROOT = Path("C:/blarai-spike-1740-mxc")
WXC = MXC_ROOT / "dl/x64/wxc-exec.exe"
STATE_DIR = MXC_ROOT / "state"
CFG_DIR = MXC_ROOT / "cfg"
LOG_DIR = MXC_ROOT / "logs"
PUBLISHED_ZIP_SHA256 = "0bb483b3592d0f663f2c5a7a2ae17db89cc04b82238684b0a1a9384b0fe828ed"
EXPECTED_SIGNER = "CN=Microsoft Corporation"
FIXTURE = Path("C:/blarai-spike-1740")
WORKTREE = FIXTURE / "worktree"
TOOLCHAIN = FIXTURE / "toolchain"
PAYLOAD_DIR = FIXTURE / "payload"
REG_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                r"\ProcessSandboxes\Mappings")
REG_AC_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                   r"\AppContainer\Mappings")
CREATE_NO_WINDOW = 0x08000000
WATCHED_ACLS = [FIXTURE, TOOLCHAIN, PAYLOAD_DIR, WORKTREE, FIXTURE / "leak", FIXTURE / "instrument",
                TOOLCHAIN / "Python314/python.exe", TOOLCHAIN / "Git/cmd/git.exe"]

NONE_NET = {"egress": {"default": "deny"}, "ingress": {"default": "deny", "hostLoopback": "deny"}}
LOOPBACK_NET = {"egress": {"default": "deny"}, "ingress": {"default": "allow", "hostLoopback": "allow"}}
NETWORK = {
    "E0": NONE_NET,
    "E1": NONE_NET,
    "E2": {"egress": {"default": "allow"}, "ingress": {"default": "deny", "hostLoopback": "deny"}},
    "E3": LOOPBACK_NET,
    "E4": LOOPBACK_NET,
}
# True = the default UI lockdown (Win32k system-call disable) stays on.
UI_LOCKDOWN = {"E0": True, "E1": False, "E2": False, "E3": False, "E4": False}
DESCRIPTION = {
    "E0": "default UI lockdown, network none (the container's defaults)",
    "E1": "UI lockdown off, network none",
    "E2": "UI lockdown off, network egress allowed",
    "E3": "UI lockdown off, direct host-loopback allow (refused on this build if unsupported)",
    "E4": "UI lockdown off, proxy mode: container pinned to the loopback listener's address and port",
}


def hidden(argv: list[str], env_extra: dict[str, str] | None = None, timeout: float = 600
           ) -> subprocess.CompletedProcess[str]:
    import os
    env = dict(os.environ)
    env["MXC_DACL_STATE_DIR"] = str(STATE_DIR)
    env.update(env_extra or {})
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                          creationflags=CREATE_NO_WINDOW, check=False)


def reg_list(key: str) -> list[str]:
    cp = hidden(["reg", "query", key])
    return sorted(line.strip() for line in cp.stdout.splitlines() if line.strip().startswith("HKEY")) if cp.returncode == 0 else ["<absent>"]


def sddl_of(path: Path) -> str:
    try:
        return w.read_descriptor(str(path)).sddl
    except OSError as exc:
        return f"<unreadable: {exc}>"


def snapshot() -> dict[str, object]:
    return {
        "acl": {str(p): hashlib.sha256(sddl_of(p).encode()).hexdigest()[:16] for p in WATCHED_ACLS},
        "process_sandboxes": reg_list(REG_MAPPINGS),
        "appcontainer_mappings": len(reg_list(REG_AC_MAPPINGS)),
        "state_dir": sorted(p.name for p in STATE_DIR.glob("*")),
    }


def launcher_checks() -> dict[str, object]:
    sig = hidden(["pwsh", "-NoProfile", "-Command",
                  f"$s=Get-AuthenticodeSignature '{WXC}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\""]).stdout.strip()
    sha = hashlib.sha256((MXC_ROOT / "dl/mxc-release-binaries.zip").read_bytes()).hexdigest()
    probe = hidden([str(WXC), "--probe"])
    try:
        probe_json = json.loads(probe.stdout)
    except ValueError:
        probe_json = {}
    return {
        "signature": sig,
        "signature_ok": sig.startswith("Valid|") and EXPECTED_SIGNER in sig,
        "zip_sha256": sha,
        "zip_sha256_matches_published": sha == PUBLISHED_ZIP_SHA256,
        "probe_rc": probe.returncode,
        "probe": probe_json,
        "tier_ok": probe_json.get("tier") == "base-container" and probe_json.get("needsDaclAugmentation") is False,
    }


def win(path: Path | str) -> str:
    return str(path).replace("/", "\\")


def build_config(variant: str, tag: str, listener_port: int, out_file: Path) -> dict[str, object]:
    py = TOOLCHAIN / "Python314/python.exe"
    cmd = (f'"{win(py)}" -I "{win(PAYLOAD_DIR / "arm_payload.py")}" --arm E --tag {tag} '
           f'--out "{win(out_file)}" --tools "{win(PAYLOAD_DIR / "tools.json")}" --listener-port {listener_port} '
           f'--operator-home "{run_arm.argv_tail(win(os.environ["USERPROFILE"]))}"')  # the OPERATOR's profile: the payload runs in the container
    cfg: dict[str, object] = {
        "version": "1.0.0",
        "containment": "processcontainer",
        "lifecycle": {"destroyOnExit": True},
        "fallback": {"allowDaclMutation": False},
        "process": {"commandLine": cmd, "cwd": win(WORKTREE), "inheritDefaultEnv": True, "timeout": 240000},
        "filesystem": {"readwritePaths": [win(WORKTREE)],
                       "readonlyPaths": [win(TOOLCHAIN), win(PAYLOAD_DIR)]},
        "network": NETWORK[variant],
    }
    if not UI_LOCKDOWN[variant]:
        cfg["ui"] = {"disable": False, "clipboard": "none", "injection": False}
    if variant == "E4":
        cfg["runtimeConfig"] = {"networkProxy": f"http://127.0.0.1:{listener_port}"}
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--variants", default="E0,E1,E2,E3,E4")
    args = ap.parse_args()
    if not (FIXTURE / "fixtures.json").exists() or not (TOOLCHAIN / "Python314").exists():
        raise SystemExit("run `run_phase2.py --stage prep` first")
    for d in (STATE_DIR, CFG_DIR, LOG_DIR, args.out):
        d.mkdir(parents=True, exist_ok=True)
    run_arm.stage_payload(run_arm.FIXTURE_TOOLS)
    checks = launcher_checks()
    (args.out / "launcher-checks.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")
    if not (checks["signature_ok"] and checks["zip_sha256_matches_published"] and checks["tier_ok"]):
        print("launcher checks failed:", json.dumps({k: v for k, v in checks.items() if k != "probe"}))
        return 3
    listener = run_arm.Listener()
    summary = []
    try:
        for variant in [v for v in args.variants.split(",") if v]:
            dest = args.out / f"arm-{variant}"
            dest.mkdir(parents=True, exist_ok=True)
            for i in range(1, args.runs + 1):
                tag = f"{variant}-{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S')}-r{i}"
                out_file = WORKTREE / f"result-{tag}.json"
                cfg = build_config(variant, tag, listener.port, out_file)
                cfg_path = CFG_DIR / f"{tag}.json"
                cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
                before = snapshot()
                dry = hidden([str(WXC), str(cfg_path), "--dry-run"])
                record: dict[str, object] = {"variant": variant, "description": DESCRIPTION[variant], "tag": tag,
                                             "config": cfg, "dry_run": {"rc": dry.returncode,
                                             "stdout": dry.stdout.strip()[-600:], "stderr": dry.stderr.strip()[-600:]},
                                             "snapshot_before": before}
                if dry.returncode != 0:
                    record["launch"] = {"skipped": "dry-run validation failed"}
                    (dest / f"run-{tag}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
                    print(tag, "dry-run failed rc", dry.returncode, dry.stderr.strip()[-200:] or dry.stdout.strip()[-200:])
                    break
                log_file = LOG_DIR / f"{tag}.log"
                accepts_before = listener.accepted
                t0 = time.perf_counter()
                cp = hidden([str(WXC), str(cfg_path), "--log-file", str(log_file)], timeout=360)
                record["launch"] = {"exit_code": cp.returncode, "wall_secs": round(time.perf_counter() - t0, 3),
                                    "listener_accepts": listener.accepted - accepts_before,
                                    "stdout_tail": cp.stdout.strip()[-800:], "stderr_tail": cp.stderr.strip()[-800:]}
                record["mxc_log_tail"] = log_file.read_text(encoding="utf-8", errors="replace")[-2500:] if log_file.exists() else ""
                if out_file.exists():
                    record["payload"] = json.loads(out_file.read_text(encoding="utf-8"))
                    out_file.unlink()
                else:
                    record["payload"] = None
                after = snapshot()
                record["snapshot_after"] = after
                changed = {k: [before[k], after[k]] for k in before if before[k] != after[k]}
                record["state_changed_by_run"] = changed
                (dest / f"run-{tag}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
                print(tag, "rc", cp.returncode, "payload" if record["payload"] else "NO PAYLOAD",
                      "STATE CHANGED " + ",".join(changed) if changed else "state unchanged", flush=True)
                summary.append({"tag": tag, "rc": cp.returncode, "changed": list(changed)})
                if changed:
                    print("stopping: a run changed watched state; see the record")
                    return 4
    finally:
        listener.close()
        (args.out / "stage-e.json").write_text(json.dumps({"runs": summary, "final_snapshot": snapshot()}, indent=1),
                                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
