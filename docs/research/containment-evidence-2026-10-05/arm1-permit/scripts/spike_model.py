"""#1689 confined-inference spike: the GPU + serve half, run by spike-run-test.ps1 AS the blarai-spike account.

Modes
  feasibility : import openvino_genai, enumerate devices, load the 4B on GPU, generate 64 tokens twice.
  serve       : same load, then a loopback-only HTTP listener (127.0.0.1, ephemeral port) that answers POST with a
                model completion (a fixed string if the model did not load) for --hold seconds, then stops; with
                --stop-file it also stops as soon as that file exists (the operator ends a server it started itself).
  --selftest  : pure helpers only. No openvino import, no GPU, no socket.

Every failure is captured in full (type, message, traceback) in the output JSON; nothing is swallowed. The model
configuration mirrors evals/cb_pipeline.py engine "cb-mtp-off" (ContinuousBatchingPipeline, the same compile
properties and scheduler) so the numbers are comparable with the in-process arm; the repo module itself is not
imported because the spike account has no read access to the repo.

Standard library + openvino_genai only. Timestamps use the machine clock with its UTC offset.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PROMPT = "Explain in three sentences why the sky is blue."
MAX_NEW_TOKENS = 64
SERVE_MAX_NEW_TOKENS = 128
MAX_BODY_BYTES = 8192
FIXED_COMPLETION = "MODEL_NOT_LOADED: fixed string from the confined spike listener"

# Mirrors evals/cb_pipeline.py _COMPILE_PROPERTIES / _CACHE_SIZE_GB / _MAX_NUM_SEQS (engine cb-mtp-off).
COMPILE_PROPERTIES = {
    "PERFORMANCE_HINT": "LATENCY",
    "INFERENCE_PRECISION_HINT": "f16",
    "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
    "CACHE_DIR": "",
    "KV_CACHE_PRECISION": "f16",
    "DYNAMIC_QUANTIZATION_GROUP_SIZE": 0,
}
CACHE_SIZE_GB = 3
MAX_NUM_SEQS = 1


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def err_record(exc: BaseException) -> dict:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def write_json_atomic(path: str, obj: object) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, sort_keys=False)
    os.replace(tmp, path)


def clamp_tokens(value: object, default: int = MAX_NEW_TOKENS, cap: int = SERVE_MAX_NEW_TOKENS) -> int:
    """Pure. A request-supplied max_new_tokens, clamped to 1..cap; junk falls back to the default."""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(cap, n))


def parse_request_body(raw: bytes) -> tuple[dict | None, str]:
    """Pure. (obj, '') on success, (None, reason) on any malformed body. Size-capped, object-only."""
    if len(raw) > MAX_BODY_BYTES:
        return None, "body too large"
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"body is not JSON: {exc}"
    if not isinstance(obj, dict):
        return None, "body must be a JSON object"
    prompt = obj.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        return None, "prompt must be a non-empty string of at most 4000 characters"
    return obj, ""


def should_stop(elapsed_s: float, hold_s: int, stop_file: str | None) -> bool:
    """Pure apart from one existence check. The serve loop ends when the hold has elapsed or the stop file exists."""
    if elapsed_s >= hold_s:
        return True
    return bool(stop_file) and os.path.exists(stop_file)


def tcp_probe(host: str, port: int, timeout: float) -> dict:
    t0 = time.perf_counter()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return {"target": f"{host}:{port}", "connected": True, "ms": round((time.perf_counter() - t0) * 1000, 1), "error": "", "t": now_iso()}
    except OSError as exc:
        return {"target": f"{host}:{port}", "connected": False, "ms": round((time.perf_counter() - t0) * 1000, 1), "error": f"{type(exc).__name__}: {exc}", "t": now_iso()}
    finally:
        s.close()


class Engine:
    """The loaded model, or a record of why it is not."""

    def __init__(self, model_dir: str, device: str) -> None:
        self.model_dir = model_dir
        self.device = device
        self.ov = None
        self.pipe = None
        self.load: dict = {"ok": False, "seconds": None, "error": None, "started": now_iso()}

    def import_runtime(self, out: dict) -> bool:
        try:
            import openvino as ov  # type: ignore
            import openvino_genai as og  # type: ignore
        except BaseException as exc:  # noqa: BLE001 - recorded in full
            out["import_error"] = err_record(exc)
            return False
        self.ov = og
        out["versions"] = {
            "python": sys.version.split()[0],
            "openvino": getattr(ov, "__version__", "?"),
            "openvino_genai": getattr(og, "__version__", "?"),
        }
        try:
            core = ov.Core()
            devs = list(core.available_devices)
            out["devices"] = devs
            names = {}
            for d in devs:
                try:
                    names[d] = str(core.get_property(d, "FULL_DEVICE_NAME"))
                except BaseException as exc:  # noqa: BLE001
                    names[d] = f"<unreadable: {type(exc).__name__}: {exc}>"
            out["device_names"] = names
        except BaseException as exc:  # noqa: BLE001
            out["device_enumeration_error"] = err_record(exc)
        return True

    def load_model(self) -> bool:
        og = self.ov
        t0 = time.perf_counter()
        try:
            sched = og.SchedulerConfig()
            sched.cache_size = CACHE_SIZE_GB
            sched.max_num_seqs = MAX_NUM_SEQS
            sched.enable_prefix_caching = False
            self.pipe = og.ContinuousBatchingPipeline(self.model_dir, sched, self.device, dict(COMPILE_PROPERTIES))
            self.load["ok"] = True
        except BaseException as exc:  # noqa: BLE001 - the GPU access error text is the make-or-break signal
            self.load["error"] = err_record(exc)
        self.load["seconds"] = round(time.perf_counter() - t0, 3)
        self.load["finished"] = now_iso()
        return bool(self.load["ok"])

    def generate(self, prompt: str, max_new_tokens: int) -> dict:
        og = self.ov
        cfg = og.GenerationConfig()
        cfg.max_new_tokens = max_new_tokens
        cfg.do_sample = False
        first: list[float] = []
        t0 = time.perf_counter()

        def tap(_chunk: str):
            if not first:
                first.append(time.perf_counter() - t0)
            return og.StreamingStatus.RUNNING

        row: dict = {"started": now_iso(), "ok": False}
        try:
            res = self.pipe.generate([prompt], [cfg], tap)[0]
            wall = time.perf_counter() - t0
            text = res.m_generation_ids[0] if res.m_generation_ids else ""
            row.update(ok=bool(text), text=str(text), wall_ms=round(wall * 1000, 1))
            if first:
                row["first_chunk_s"] = round(first[0], 4)
            pm = getattr(res, "perf_metrics", None)
            if pm is not None:
                try:
                    n = int(pm.get_num_generated_tokens())
                    row["generated_tokens"] = n
                    row["ttft_ms"] = round(float(pm.get_ttft().mean), 2)
                    row["tpot_ms"] = round(float(pm.get_tpot().mean), 2)
                    row["tok_per_s_wall"] = round(n / wall, 2) if wall > 0 else None
                    row["tok_per_s_tpot"] = round(1000.0 / row["tpot_ms"], 2) if row["tpot_ms"] else None
                except BaseException as exc:  # noqa: BLE001
                    row["metrics_error"] = err_record(exc)
        except BaseException as exc:  # noqa: BLE001
            row["error"] = err_record(exc)
        row["finished"] = now_iso()
        return row


def make_handler(engine: Engine | None, log: list, state: dict):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BlarAISpike/1"

        def log_message(self, *_a):  # no stderr noise; requests are recorded in `log`
            return

        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            self._send(200, {"ok": True, "model_loaded": engine is not None, "t": now_iso()})

        def do_POST(self):  # noqa: N802
            t0 = time.perf_counter()
            entry = {"t": now_iso(), "peer": self.client_address[0], "path": self.path}
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY_BYTES:
                entry["status"] = 413
                log.append(entry)
                self._send(413, {"error": "bad or oversized Content-Length"})
                return
            obj, why = parse_request_body(self.rfile.read(n))
            if obj is None:
                entry["status"] = 400
                entry["error"] = why
                log.append(entry)
                self._send(400, {"error": why})
                return
            if engine is None:
                entry.update(status=200, model="fixed-string")
                log.append(entry)
                self._send(200, {"completion": FIXED_COMPLETION, "model_loaded": False, "t": now_iso()})
                return
            row = engine.generate(obj["prompt"], clamp_tokens(obj.get("max_new_tokens")))
            entry.update(status=200 if row.get("ok") else 500, model="model", wall_ms=round((time.perf_counter() - t0) * 1000, 1),
                         generated_tokens=row.get("generated_tokens"), ttft_ms=row.get("ttft_ms"))
            if not row.get("ok"):
                entry["error"] = row.get("error")
            log.append(entry)
            self._send(entry["status"], {"completion": row.get("text", ""), "model_loaded": True,
                                         "generated_tokens": row.get("generated_tokens"), "wall_ms": row.get("wall_ms"),
                                         "ran_as_pid": os.getpid(), "t": now_iso()})

    return Handler


def serve(engine: Engine | None, hold_s: int, port_file: str, run_id: str, outbound: tuple[str, int, float], out: dict,
          stop_file: str | None = None) -> None:
    log: list = []
    state: dict = {}
    srv = HTTPServer(("127.0.0.1", 0), make_handler(engine, log, state))
    host, port = srv.server_address[0], srv.server_address[1]
    if host != "127.0.0.1":  # fail closed: never a non-loopback bind
        srv.server_close()
        raise RuntimeError(f"listener bound to {host}, refusing")
    srv.timeout = 1.0
    started = time.monotonic()
    rec = {"bind": f"{host}:{port}", "hold_seconds": hold_s, "started": now_iso(), "model_loaded": engine is not None,
           "pid": os.getpid(), "stop_file": stop_file}
    out["serve"] = rec
    write_json_atomic(port_file, {"run_id": run_id, "host": host, "port": port, "pid": os.getpid(),
                                  "model_loaded": engine is not None, "hold_seconds": hold_s, "t": now_iso()})
    mid_done = False
    try:
        while not should_stop(time.monotonic() - started, hold_s, stop_file):
            srv.handle_request()
            if not mid_done and time.monotonic() - started >= hold_s / 2:
                rec["outbound_probe_mid_hold"] = tcp_probe(outbound[0], outbound[1], outbound[2])
                mid_done = True
    finally:
        srv.server_close()
        rec["stopped_by"] = "stop_file" if (stop_file and os.path.exists(stop_file)) else "hold"
        rec["finished"] = now_iso()
        rec["requests"] = log
        rec["requests_served"] = len([e for e in log if e.get("status") == 200])


def selftest() -> int:
    fails = []

    def check(name: str, cond: bool) -> None:
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            fails.append(name)

    check("clamp: junk -> default", clamp_tokens("x") == MAX_NEW_TOKENS and clamp_tokens(None) == MAX_NEW_TOKENS)
    check("clamp: 0 -> 1, 10**6 -> cap", clamp_tokens(0) == 1 and clamp_tokens(10**6) == SERVE_MAX_NEW_TOKENS)
    check("body: valid", parse_request_body(b'{"prompt":"hi"}')[0] == {"prompt": "hi"})
    check("body: not json", parse_request_body(b"nope")[0] is None)
    check("body: array rejected", parse_request_body(b"[1]")[0] is None)
    check("body: empty prompt rejected", parse_request_body(b'{"prompt":"  "}')[0] is None)
    check("body: oversize rejected", parse_request_body(b"x" * (MAX_BODY_BYTES + 1))[0] is None)
    check("body: non-utf8 rejected", parse_request_body(b"\xff\xfe{}")[0] is None)
    try:
        raise ValueError("boom")
    except ValueError as exc:
        r = err_record(exc)
    check("err_record carries type, message, traceback", r["type"] == "ValueError" and r["message"] == "boom" and "Traceback" in r["traceback"])
    check("now_iso has a UTC offset", now_iso()[-6] in "+-" or now_iso().endswith("Z"))
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        flag = os.path.join(td, "stop.flag")
        check("should_stop: hold not elapsed, no flag -> keep serving", should_stop(1.0, 10, flag) is False)
        check("should_stop: hold elapsed -> stop", should_stop(10.0, 10, None) is True)
        open(flag, "w", encoding="utf-8").close()
        check("should_stop: flag present before the hold elapsed -> stop", should_stop(1.0, 10, flag) is True)
    check("compile properties mirror cb-mtp-off (no draft_model)", "draft_model" not in COMPILE_PROPERTIES and COMPILE_PROPERTIES["KV_CACHE_PRECISION"] == "f16")
    # Handler against a no-model listener on loopback, in-process: proves the fixed-string path and the body gates.
    import threading
    import urllib.request
    log: list = []
    srv = HTTPServer(("127.0.0.1", 0), make_handler(None, log, {}))
    srv.timeout = 1.0
    port = srv.server_address[1]
    th = threading.Thread(target=lambda: [srv.handle_request() for _ in range(3)], daemon=True)
    th.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=b'{"prompt":"hello"}', method="POST")
        body = json.loads(urllib.request.urlopen(req, timeout=5).read())
        check("loopback POST with no model returns the fixed string", body.get("completion") == FIXED_COMPLETION and body.get("model_loaded") is False)
        bad = urllib.request.Request(f"http://127.0.0.1:{port}/", data=b"junk", method="POST")
        try:
            urllib.request.urlopen(bad, timeout=5)
            check("loopback POST with junk is rejected", False)
        except urllib.error.HTTPError as exc:
            check("loopback POST with junk is rejected (400)", exc.code == 400)
        body = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read())
        check("loopback GET health", body.get("ok") is True)
    finally:
        th.join(timeout=5)
        srv.server_close()
    check("two POSTs + one GET logged as 2 entries", len(log) == 2)
    print(f"python selftest: {'FAIL ' + str(fails) if fails else 'all passed'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mode", choices=["feasibility", "serve"])
    ap.add_argument("--model-dir")
    ap.add_argument("--out-json")
    ap.add_argument("--port-file")
    ap.add_argument("--stop-file", help="serve mode: stop as soon as this file exists (operator-run server)")
    ap.add_argument("--run-id", default="selftest")
    ap.add_argument("--hold", type=int, default=45)
    ap.add_argument("--device", default="GPU")
    ap.add_argument("--no-model", action="store_true", help="skip the load (low-memory abort); serve answers a fixed string")
    ap.add_argument("--outbound", default="1.1.1.1:443")
    ap.add_argument("--outbound-timeout", type=float, default=5.0)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.mode and a.model_dir and a.out_json):
        print("--mode, --model-dir and --out-json are required", file=sys.stderr)
        return 2
    host, _, p = a.outbound.rpartition(":")
    out: dict = {"mode": a.mode, "started": now_iso(), "pid": os.getpid(), "model_dir": a.model_dir, "device_requested": a.device, "prompt": PROMPT}
    rc = 0
    engine: Engine | None = None
    try:
        eng = Engine(a.model_dir, a.device)
        runtime_ok = eng.import_runtime(out)
        out["runtime_imported"] = runtime_ok
        if a.no_model:
            out["model_skipped"] = "low memory abort"
        elif runtime_ok:
            if eng.load_model():
                engine = eng
            out["load"] = eng.load
        if engine is not None:
            out["runs"] = []
            for i in (1, 2):
                row = engine.generate(PROMPT, MAX_NEW_TOKENS)
                row["index"] = i
                out["runs"].append(row)
        if a.mode == "serve":
            if not a.port_file:
                raise RuntimeError("--port-file required in serve mode")
            serve(engine, a.hold, a.port_file, a.run_id, (host, int(p), a.outbound_timeout), out, a.stop_file)
    except BaseException as exc:  # noqa: BLE001
        out["fatal"] = err_record(exc)
        rc = 1
    finally:
        out["finished"] = now_iso()
        try:
            write_json_atomic(a.out_json, out)
        except BaseException as exc:  # noqa: BLE001
            print(f"could not write {a.out_json}: {exc}", file=sys.stderr)
            rc = rc or 3
    return rc


if __name__ == "__main__":
    sys.exit(main())
