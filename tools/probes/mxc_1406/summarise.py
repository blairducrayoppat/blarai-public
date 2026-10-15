"""Condense the per-run records of the MXC #1406 probe into docs/performance/mxc_1406_probe_2026-10-11/summary.json."""

from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
D = ROOT / "docs/research/windows-containment-comparison-2026-10/mxc-1406-probe"
P = ROOT / "docs/performance/mxc_1406_probe_2026-10-11"


def main() -> None:
    P.mkdir(parents=True, exist_ok=True)
    runs = []
    for sub in ("raw", "raw-p18100"):
        for f in sorted(glob.glob(str(D / sub / "run-*.json"))):
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            p = d.get("payload") or {}
            runs.append({
                "condition": d["condition"], "tag": d["tag"], "record": f"{sub}/{Path(f).name}",
                "dry_run_rc": d["dry_run"]["rc"],
                "dry_run_message": (d["dry_run"]["stderr"] or d["dry_run"]["stdout"]).split("\n")[0][:200],
                "launch_exit": d["launch"].get("exit_code"), "wall_secs": d["launch"].get("wall_secs"),
                "listener_hits": d["verdict"],
                "container_tcp": [(t["target"], t.get("connected"), t.get("winerror")) for t in p.get("tcp", [])],
                "dns_example_com": (p.get("dns") or {}).get("resolved"),
                "proxied_clients": ({"urllib": p["urllib_env_proxy"].get("status"), "curl_rc": p["curl"].get("rc"),
                                     "winhttp_default": p["winhttp_default"].get("status"),
                                     "winhttp_automatic": p["winhttp_automatic"].get("status")} if p else None),
                "cpu_total_pct_before": d["machine"]["cpu_total"],
                "ac_power": d["machine"]["battery"][0]["BatteryStatus"] == 2,
                "verify_clean_rc": d["verify_clean"]["rc"], "state_changed": d["state_changed_by_run"]})
    h = json.loads((D / "raw/batch-header.json").read_text(encoding="utf-8"))
    out = {"date": "2026-10-11", "ticket": "#1746 item a", "mxc_commit": "70fc7d52 (PR #1406, self-built, Rust 1.93)",
           "windows": h["windows"], "main_launcher_sha256": h["main_launcher"]["sha256"],
           "v100_launcher_sha256": h["v100_launcher"]["sha256"], "priority": "BelowNormal", "runs": runs}
    (P / "summary.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(len(runs), "runs")


if __name__ == "__main__":
    main()
