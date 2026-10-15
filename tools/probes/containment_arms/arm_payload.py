"""In-arm probe payload for the #1740 containment comparison.

Runs INSIDE the setup being measured (launched by ``run_arm.py``, or by the operator's
arm-A script as the dedicated account). Writes one JSON result and nothing else of
lasting effect: every probe file it creates in a fixture is deleted again, and it never
writes to a real (non-fixture) path. It never reads the contents or names inside a
secret path; it records only whether the open succeeded.

Probes: identity of its own token; toolchain (node, git, git-bash, Python, opencode, and
one small task end to end in the worktree fixture); loopback (the model proxy and model
server ports, plus a throwaway listener the launcher runs); file reach (secret paths,
fixture writes); egress (raw IP and DNS name, port 443); child and grandchild inheritance.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FIXTURE_ROOT = Path("C:/blarai-spike-1740")
# The OPERATOR's profile, passed by the launcher (which runs as the operator) with --operator-home. It is never read from
# this process's own environment: arm A runs this payload as the coder account, whose USERPROFILE is its own profile, and
# the question is whether that account can read the operator's stores. No default: a missing argument fails the run.
SECRET_PATHS: list[Path] = []


def secret_paths(operator_home: Path) -> list[Path]:
    return [operator_home / ".ssh", operator_home / ".git-credentials", operator_home / "AppData/Local/BlarAI",
            operator_home / ".config/opencode", operator_home / ".codex/.sandbox-secrets"]
CREATE_NO_WINDOW = 0x08000000


def _now() -> float:
    return time.perf_counter()


def identity() -> dict[str, object]:
    try:
        import winsec as w
        return w.describe_token(w.process_token(w.TOKEN_QUERY))
    except Exception as exc:  # noqa: BLE001 - the probe records any failure and carries on
        return {"error": repr(exc)}


def run_cmd(argv: list[str], cwd: Path | None = None, timeout: float = 60) -> dict[str, object]:
    t0 = _now()
    try:
        cp = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                            creationflags=CREATE_NO_WINDOW, check=False)
        return {"argv": argv, "rc": cp.returncode, "secs": round(_now() - t0, 3),
                "out": cp.stdout.strip()[:200], "err": cp.stderr.strip()[:300]}
    except Exception as exc:  # noqa: BLE001 - recorded in the result, never raised
        return {"argv": argv, "rc": None, "secs": round(_now() - t0, 3), "error": repr(exc)[:300]}


def toolchain(tools: dict[str, str], workdir: Path, tag: str) -> dict[str, object]:
    res: dict[str, object] = {}
    res["node"] = run_cmd([tools["node"], "--version"])
    res["git"] = run_cmd([tools["git"], "--version"])
    res["bash"] = run_cmd([tools["bash"], "-lc", "echo bash-ok; uname -s"])
    res["python"] = run_cmd([tools["python"], "-I", "-c", "import sys; print(sys.version)"])
    res["opencode"] = run_cmd([tools["opencode"], "--version"], timeout=120)
    # One small real task end to end: a repo, a Python-written file, a node-computed
    # file, a git-bash step, a commit.
    repo = workdir / f"task-{tag}"
    steps = []
    t0 = _now()
    try:
        repo.mkdir(parents=True, exist_ok=False)
        g = [tools["git"], "-c", "user.name=probe", "-c", "user.email=probe@local",
             "-c", "core.hooksPath=NUL", "-c", "init.defaultBranch=main"]
        steps.append(run_cmd(g + ["init", "-q"], cwd=repo))
        steps.append(run_cmd([tools["python"], "-I", "-c",
                              "open('a.txt','w').write('alpha\\n')"], cwd=repo))
        steps.append(run_cmd([tools["node"], "-e",
                              "require('fs').writeFileSync('b.txt', String(6*7)+'\\n')"],
                             cwd=repo))
        steps.append(run_cmd([tools["bash"], "-c", "cat a.txt b.txt > c.txt && wc -l c.txt"],
                             cwd=repo))
        steps.append(run_cmd(g + ["add", "a.txt", "b.txt", "c.txt"], cwd=repo))
        steps.append(run_cmd(g + ["commit", "-q", "-m", "probe"], cwd=repo))
        steps.append(run_cmd(g + ["log", "--oneline", "-1"], cwd=repo))
        ok = all(s.get("rc") == 0 for s in steps) and (repo / "c.txt").exists()
    except Exception as exc:  # noqa: BLE001 - recorded in the result, never raised
        steps.append({"error": repr(exc)[:300]})
        ok = False
    res["task"] = {"ok": ok, "secs": round(_now() - t0, 3), "steps": steps}
    return res


def connect(host: str, port: int, timeout: float = 5.0) -> dict[str, object]:
    t0 = _now()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"target": f"{host}:{port}", "result": "connected",
                    "secs": round(_now() - t0, 3)}
    except OSError as exc:
        return {"target": f"{host}:{port}", "result": "failed",
                "winerror": getattr(exc, "winerror", None), "errno": exc.errno,
                "error": type(exc).__name__, "secs": round(_now() - t0, 3)}


def try_open(path: Path) -> str:
    try:
        if path.is_dir():
            with os.scandir(path) as it:
                next(it, None)
        else:
            with open(path, "rb") as fh:
                fh.read(0)
        return "allowed"
    except FileNotFoundError:
        return "absent"
    except PermissionError:
        return "denied"
    except OSError as exc:
        return f"error:{getattr(exc, 'winerror', exc.errno)}"


def try_write(folder: Path, tag: str) -> str:
    probe = folder / f"probe-{tag}.txt"
    try:
        with open(probe, "x", encoding="ascii") as fh:
            fh.write("probe")
    except FileExistsError:
        return "error:exists"
    except PermissionError:
        return "denied"
    except OSError as exc:
        return f"error:{getattr(exc, 'winerror', exc.errno)}"
    try:
        probe.unlink()
        return "allowed"
    except OSError:
        return "allowed-undeletable"


def file_reach(tag: str) -> dict[str, object]:
    reads = {str(p): try_open(p) for p in SECRET_PATHS}
    writes = {}
    for sub in ("leak", "instrument"):
        base = FIXTURE_ROOT / sub
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir():
                    writes[str(d)] = try_write(d, tag)
    writes[str(FIXTURE_ROOT / "worktree")] = try_write(FIXTURE_ROOT / "worktree", tag)
    return {"secret_reads": reads, "fixture_writes": writes}


def egress() -> list[dict[str, object]]:
    return [connect("1.1.1.1", 443), connect("example.com", 443)]


def loopback(listener_port: int) -> list[dict[str, object]]:
    out = [connect("127.0.0.1", 8099, 3), connect("127.0.0.1", 8000, 3)]
    if listener_port:
        out.append(connect("127.0.0.1", listener_port, 3))
    return out


def inheritance(depth: int, args: argparse.Namespace) -> dict[str, object]:
    me: dict[str, object] = {
        "depth": depth,
        "identity": identity(),
        "write_authusers": try_write(FIXTURE_ROOT / "leak/authenticated-users-modify",
                                     f"{args.tag}-d{depth}"),
        "egress": connect("1.1.1.1", 443, 5),
    }
    if depth < 2:
        cp = subprocess.run([sys.executable, "-I", __file__, "--child", str(depth + 1),
                             "--tag", args.tag], capture_output=True, text=True,
                            timeout=60, creationflags=CREATE_NO_WINDOW, check=False)
        try:
            me["child"] = json.loads(cp.stdout)
        except ValueError:
            me["child"] = {"error": "no JSON", "rc": cp.returncode, "err": cp.stderr[-300:]}
    return me


def main() -> int:
    ap = argparse.ArgumentParser(description="In-arm probes for #1740.")
    ap.add_argument("--arm", default="")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--tools", type=Path)
    ap.add_argument("--listener-port", type=int, default=0)
    ap.add_argument("--child", type=int, default=0)
    ap.add_argument("--skip-egress", action="store_true")
    ap.add_argument("--operator-home", type=Path, required=True, help="the OPERATOR's profile directory (the launcher passes its own USERPROFILE)")
    args = ap.parse_args()
    SECRET_PATHS[:] = secret_paths(args.operator_home)
    if args.child:
        print(json.dumps(inheritance(args.child, args)))
        return 0
    tools = json.loads(args.tools.read_text(encoding="utf-8"))
    t0 = _now()
    result = {
        "arm": args.arm, "tag": args.tag,
        "started": dt.datetime.now().astimezone().astimezone().isoformat(timespec="seconds"),
        "identity": identity(),
        "toolchain": toolchain(tools, FIXTURE_ROOT / "worktree", args.tag),
        "loopback": loopback(args.listener_port),
        "file_reach": file_reach(args.tag),
        "egress": [] if args.skip_egress else egress(),
        "inheritance": inheritance(0, args),
    }
    result["total_secs"] = round(_now() - t0, 3)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
