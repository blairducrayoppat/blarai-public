"""Import-only smoke payload for the MXC denied-subtree probe.

WHAT IT DOES. Runs inside a throwaway container, under the same policy shape as the measured runs, before
any measured launch. It imports ctypes, _winapi and ctypes.wintypes, imports the measured payload module from
its own directory, makes one directory listing of T through that module's Win32 wrappers, and writes a JSON
report to --out. It writes nothing else and touches nothing outside T.

WHY. A payload that cannot even import inside the container (for example ctypes failing to initialise under a
UI restriction) would otherwise surface as a launch with no report. The harness runs this first and stops with
CONTAINER-PAYLOAD-BROKEN, before any S2 attempt, when the report is missing or any step failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    out = Path(sys.argv[sys.argv.index("--out") + 1])
    t = Path(sys.argv[sys.argv.index("--t") + 1])
    rep: dict[str, object] = {"steps": {}}
    for name in ("ctypes", "_winapi", "ctypes.wintypes", "payload"):
        try:
            __import__(name)
            rep["steps"][name] = "ok"  # type: ignore[index]
        except Exception as exc:  # noqa: BLE001 - recorded
            rep["steps"][name] = f"{type(exc).__name__}: {exc}"[:300]  # type: ignore[index]
    if rep["steps"]["payload"] == "ok":  # type: ignore[index]
        import payload  # noqa: PLC0415

        res = payload._rec(lambda: payload.list_dir(t))
        rep["steps"]["list_dir"] = "ok" if res["ok"] else f"winerror {res['winerror']}"  # type: ignore[index]
    rep["ok"] = all(v == "ok" for v in rep["steps"].values())  # type: ignore[union-attr]
    out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
