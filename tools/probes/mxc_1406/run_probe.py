"""MXC PR #1406 loopback-proxy probe (#1746 item a): harness, listeners and condition runner.

Conditions (each run is a separate launcher invocation, always preceded by --dry-run):
  T-on     main build, unpackaged non-AppContainer proxy config (egress deny, ingress allow + hostLoopback allow,
           runtimeConfig.networkProxy http://127.0.0.1:<port>, no allowedProxyPeer)
  L-off-a  main build, same config WITHOUT runtimeConfig.networkProxy (lock off)
  L-off-b  main build, T-on with ingress.hostLoopback=deny (lock off)
  L-off-c  main build, no proxy, ingress deny, loopback deny, egress deny (plain baseline)
  V100     Microsoft-signed v1.0.0 launcher, the T-on config
  P-18100  main build, T-on with the proxy endpoint moved to the second port (scoping discriminator)

Success is judged from the HOST-SIDE listener log. The listeners are throwaway, bind only 127.0.0.1 / the LAN
address on the probe ports, and never touch the real model server ports.

Run elevated: python -I run_probe.py --out <dir> [--runs 3] [--conditions L-off-c,L-off-a,L-off-b,T-on,V100]
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "containment_arms"))
import winsec as w  # noqa: E402

MXC_ROOT = Path("C:/blarai-spike-1740-mxc")
WORK_ROOT = MXC_ROOT / "probe1406"
MAIN_WXC = MXC_ROOT / "build1406/target/x86_64-pc-windows-msvc/release/wxc-exec.exe"
V100_WXC = MXC_ROOT / "dl/x64/wxc-exec.exe"
STATE_DIR = WORK_ROOT / "state"
CFG_DIR = WORK_ROOT / "cfg"
LOG_DIR = WORK_ROOT / "logs"
PAYLOAD_DIR = WORK_ROOT / "payload"
WORK_DIR = WORK_ROOT / "work"
TOOLCHAIN = Path("C:/blarai-spike-1740/toolchain")
PY = TOOLCHAIN / "Python314/python.exe"
PORT, OTHER_PORT = 18099, 18100
PWSH = "C:/Program Files/PowerShell/7/pwsh.exe"
REG_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                r"\ProcessSandboxes\Mappings")
REG_AC_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                   r"\AppContainer\Mappings")
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000
WATCHED = [WORK_ROOT, PAYLOAD_DIR, WORK_DIR, TOOLCHAIN, TOOLCHAIN / "Python314/python.exe"]


def hidden(argv: list[str], timeout: float = 600) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["MXC_DACL_STATE_DIR"] = str(STATE_DIR)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                          creationflags=CREATE_NO_WINDOW | BELOW_NORMAL, check=False)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class ProbeListener:
    """Throwaway TCP/HTTP listener that logs every connection (timestamp, peer, request line, marker header)."""

    def __init__(self, name: str, host: str, port: int, log: list[dict[str, object]], lock: threading.Lock) -> None:
        self.name, self.host, self.port, self.log, self.lock = name, host, port, log, lock
        self.sock = socket.socket()
        self.sock.bind((host, port))
        self.sock.listen(16)
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while self.alive:
            try:
                conn, peer = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn, peer), daemon=True).start()

    def _handle(self, conn: socket.socket, peer: tuple[str, int]) -> None:
        ts = now_iso()
        data = b""
        conn.settimeout(2.0)
        try:
            while b"\r\n\r\n" not in data and len(data) < 4096:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
        except OSError:
            pass
        lines = data.decode("latin-1", "replace").split("\r\n")
        marker = next((ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("x-probe-marker:")), "")
        entry = {"ts": ts, "listener": self.name, "bind": f"{self.host}:{self.port}", "peer": f"{peer[0]}:{peer[1]}",
                 "request_line": lines[0][:200], "marker": marker, "bytes": len(data)}
        with self.lock:
            self.log.append(entry)
        try:
            body = f"listener-{self.name}-ok".encode()
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        except OSError:
            pass
        conn.close()

    def close(self) -> None:
        self.alive = False
        self.sock.close()


def host_control(host: str, port: int, marker: str) -> str:
    try:
        with socket.create_connection((host, port), timeout=3) as s:
            s.sendall(f"GET /{marker} HTTP/1.0\r\nX-Probe-Marker: {marker}\r\n\r\n".encode())
            return s.recv(200).decode("latin-1", "replace").split("\r\n")[0]
    except OSError as exc:
        return f"FAILED {exc!r}"


def lan_ip() -> str:
    cp = hidden([PWSH, "-NoProfile", "-Command",
                 "(Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Sort-Object RouteMetric | Select-Object -First 1 |"
                 " ForEach-Object { (Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4).IPAddress })"
                 " | Select-Object -First 1"])
    return cp.stdout.strip().splitlines()[0].strip()


def reg_list(key: str) -> list[str]:
    cp = hidden(["reg", "query", key])
    return (sorted(ln.strip() for ln in cp.stdout.splitlines() if ln.strip().startswith("HKEY"))
            if cp.returncode == 0 else ["<absent>"])


def snapshot() -> dict[str, object]:
    def sddl(p: Path) -> str:
        try:
            return w.read_descriptor(str(p)).sddl
        except OSError as exc:
            return f"<unreadable: {exc}>"
    return {"acl": {str(p): hashlib.sha256(sddl(p).encode()).hexdigest()[:16] for p in WATCHED},
            "process_sandboxes": reg_list(REG_MAPPINGS), "appcontainer_mappings": len(reg_list(REG_AC_MAPPINGS)),
            "state_dir": sorted(p.name for p in STATE_DIR.glob("*"))}


MACHINE_PS = r"""
$o=[ordered]@{}
$o.battery=@(Get-CimInstance Win32_Battery | Select-Object BatteryStatus,EstimatedChargeRemaining)
$o.top_cpu=@(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | Where-Object {$_.Name -notin '_Total','Idle'} | Sort-Object PercentProcessorTime -Descending | Select-Object -First 5 | ForEach-Object {"$($_.Name)=$($_.PercentProcessorTime)"})
$o.cpu_total=(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime
$o.bitdefender=@(Get-Process | Where-Object {$_.ProcessName -match 'bd|bitdefender|vsserv|epsecurity|epintegration|updatesrv|seccenter|epprotected'} | ForEach-Object {"$($_.ProcessName)/$($_.Id)"})
try { $o.thermal_c=@(Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature -ErrorAction Stop | ForEach-Object {[math]::Round($_.CurrentTemperature/10-273.15,1)}) } catch { $o.thermal_c="unavailable" }
$o | ConvertTo-Json -Compress -Depth 4
"""


def machine_conditions() -> object:
    cp = hidden([PWSH, "-NoProfile", "-Command", MACHINE_PS], timeout=120)
    try:
        return json.loads(cp.stdout)
    except ValueError:
        return {"error": cp.stdout[-300:] + cp.stderr[-300:]}


def win(p: Path | str) -> str:
    return str(p).replace("/", "\\")


def build_config(cond: str, tag: str, lan: str) -> dict[str, object]:
    out = WORK_DIR / f"result-{tag}.json"
    cmd = (f'"{win(PY)}" -I "{win(PAYLOAD_DIR / "net_payload.py")}" --tag {tag} --out "{win(out)}" '
           f'--lan-ip {lan} --port {PORT} --other-port {OTHER_PORT}')
    loopback_allow = cond in ("T-on", "L-off-a", "V100", "P-18100")
    net: dict[str, object] = {"egress": {"default": "deny"},
                              "ingress": {"default": "deny" if cond == "L-off-c" else "allow",
                                          "hostLoopback": "allow" if loopback_allow else "deny"}}
    cfg: dict[str, object] = {
        "version": "1.0.0", "containment": "processcontainer", "lifecycle": {"destroyOnExit": True},
        "fallback": {"allowDaclMutation": False},
        "process": {"commandLine": cmd, "cwd": win(WORK_DIR), "inheritDefaultEnv": True, "timeout": 150000},
        "filesystem": {"readwritePaths": [win(WORK_DIR)], "readonlyPaths": [win(TOOLCHAIN), win(PAYLOAD_DIR)]},
        "network": net,
        "ui": {"disable": False, "clipboard": "none", "injection": False},
    }
    if cond in ("T-on", "L-off-b", "V100"):
        cfg["runtimeConfig"] = {"networkProxy": f"http://127.0.0.1:{PORT}"}
    if cond == "P-18100":
        cfg["runtimeConfig"] = {"networkProxy": f"http://127.0.0.1:{OTHER_PORT}"}
    return cfg


def launcher_info(exe: Path) -> dict[str, object]:
    probe = hidden([str(exe), "--probe"])
    try:
        pj = json.loads(probe.stdout)
    except ValueError:
        pj = {"unparsed": probe.stdout[-300:]}
    sig = hidden([PWSH, "-NoProfile", "-Command",
                  f"$s=Get-AuthenticodeSignature '{exe}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\""]).stdout.strip()
    return {"path": str(exe), "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "size": exe.stat().st_size,
            "signature": sig, "probe_rc": probe.returncode, "probe": pj}


def verify_clean(out: Path) -> dict[str, object]:
    cp = hidden([sys.executable, "-I", str(HERE.parent / "containment_arms/run_phase2.py"), "--stage", "verify-clean",
                 "--out", str(out)], timeout=300)
    try:
        j = json.loads(cp.stdout)
    except ValueError:
        j = {"unparsed": cp.stdout[-300:]}
    return {"rc": cp.returncode, "state": j.get("state"), "stderr": cp.stderr[-200:]}


def verdict_of(real: list[dict[str, object]]) -> dict[str, object]:
    def hits(listener: str) -> list[dict[str, object]]:
        return [e for e in real if e["listener"] == listener]
    l99 = hits("loop18099")
    return {
        "loop18099_hits": len(l99),
        "loop18099_direct_marker": any("direct-loop18099" in str(e["marker"]) + str(e["request_line"]) for e in l99),
        "loop18099_proxied_request_lines": [e["request_line"] for e in l99 if "mxc-proxy-probe" in str(e["request_line"])],
        "loop18100_hits": len(hits("loop18100")),
        "lan18099_hits": len(hits("lan18099")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--conditions", default="L-off-c,L-off-a,L-off-b,T-on,V100")
    args = ap.parse_args()
    kernel32 = ctypes.windll.kernel32
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL)
    for d in (STATE_DIR, CFG_DIR, LOG_DIR, PAYLOAD_DIR, WORK_DIR, args.out):
        d.mkdir(parents=True, exist_ok=True)
    (PAYLOAD_DIR / "net_payload.py").write_bytes((HERE / "net_payload.py").read_bytes())
    lan = lan_ip()
    head: dict[str, object] = {
        "started": now_iso(), "lan_ip": lan, "host_python": sys.version, "main_launcher": launcher_info(MAIN_WXC),
        "v100_launcher": launcher_info(V100_WXC), "machine_start": machine_conditions(),
        "windows": hidden(["cmd", "/c", "ver"]).stdout.strip(), "priority": "BelowNormal"}
    (args.out / "batch-header.json").write_text(json.dumps(head, indent=1), encoding="utf-8")
    if head["main_launcher"]["probe"].get("tier") != "base-container":  # type: ignore[index]
        print("launcher tier not base-container; stopping")
        return 3
    summary: list[dict[str, object]] = []
    for i in range(1, args.runs + 1):
        for cond in [c for c in args.conditions.split(",") if c]:
            tag = f"{cond}-r{i}-{datetime.now().strftime('%H%M%S')}"
            exe = V100_WXC if cond == "V100" else MAIN_WXC
            cfg = build_config(cond, tag, lan)
            cfg_path = CFG_DIR / f"{tag}.json"
            cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
            log: list[dict[str, object]] = []
            lock = threading.Lock()
            ls = [ProbeListener("loop18099", "127.0.0.1", PORT, log, lock),
                  ProbeListener("loop18100", "127.0.0.1", OTHER_PORT, log, lock),
                  ProbeListener("lan18099", lan, PORT, log, lock)]
            rec: dict[str, object] = {"condition": cond, "tag": tag, "run": i, "launcher": str(exe), "config": cfg,
                                      "machine": machine_conditions(), "snapshot_before": snapshot()}
            rec["host_control"] = {x.name: host_control(x.host, x.port, f"host-control-{x.name}") for x in ls}
            dry = hidden([str(exe), str(cfg_path), "--dry-run"])
            rec["dry_run"] = {"rc": dry.returncode, "stdout": dry.stdout.strip()[-800:],
                              "stderr": dry.stderr.strip()[-800:]}
            if dry.returncode == 0:
                logf = LOG_DIR / f"{tag}.log"
                t0 = time.perf_counter()
                started = now_iso()
                try:
                    cp = hidden([str(exe), str(cfg_path), "--log-file", str(logf)], timeout=300)
                    rec["launch"] = {"exit_code": cp.returncode, "wall_secs": round(time.perf_counter() - t0, 3),
                                     "started": started, "stdout": cp.stdout.strip()[-1500:],
                                     "stderr": cp.stderr.strip()[-800:]}
                except subprocess.TimeoutExpired:
                    rec["launch"] = {"timeout": True, "started": started}
                rec["mxc_log_tail"] = (logf.read_text(encoding="utf-8", errors="replace")[-3000:]
                                       if logf.exists() else "")
                out = WORK_DIR / f"result-{tag}.json"
                rec["payload"] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
                if out.exists():
                    out.unlink()
            else:
                rec["launch"] = {"skipped": "dry-run rejected the config"}
            time.sleep(0.5)
            for x in ls:
                x.close()
            with lock:
                real = [e for e in log if not str(e["marker"]).startswith("host-control")]
                rec["listener_log_all"] = list(log)
            rec["container_attributed_log"] = real
            rec["verdict"] = verdict_of(real)
            rec["snapshot_after"] = snapshot()
            vc = verify_clean(args.out / "verify-clean")
            rec["verify_clean"] = vc
            before, after = rec["snapshot_before"], rec["snapshot_after"]
            changed = {k: [before[k], after[k]] for k in before if before[k] != after[k]}  # type: ignore[index]
            rec["state_changed_by_run"] = changed
            (args.out / f"run-{tag}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
            line = {"tag": tag, "dry_rc": dry.returncode, "launch_rc": rec["launch"].get("exit_code"),  # type: ignore[union-attr]
                    "verdict": rec["verdict"], "verify_clean_rc": vc["rc"], "state_changed": list(changed)}
            summary.append(line)
            print(json.dumps(line), flush=True)
            (args.out / "batch-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
            if changed or vc["rc"] != 0:
                print("STOP: leftover or changed state; see the record")
                return 4
    head["finished"] = now_iso()
    head["machine_end"] = machine_conditions()
    (args.out / "batch-header.json").write_text(json.dumps(head, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
