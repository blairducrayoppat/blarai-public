"""
Thinking-toggle probe under llama-server (#769 item 3 — feeds genai #3937)
==========================================================================
The OpenVINO GenAI probe (`scripts/probe_qwen36_thinking_toggle.py`, 2026-07-08)
found `/no_think` ignored + untagged visible thinking on Qwen3.6 — the genai
#3937 class, and the blocker for the PA's `/no_think` mechanism (ADR-012 §2.4).
llama.cpp's chat-template handling is independent of the OpenVINO IR export, so
a works/doesn't-work result here isolates whether the #3937 behaviour is
backend-specific or model-intrinsic.

Per model (Qwen3.6-27B dense, Qwen3.6-35B-A3B MoE — the thread's model), this
driver starts `llama-server` (b9957 win-vulkan, -ngl 99), waits for /health,
then probes the OpenAI-compatible /v1/chat/completions endpoint:

  A. plain prompt                              -> model default (thinking ON?)
  B. prompt + '/no_think' soft switch          -> the production PA mechanism
  C. chat_template_kwargs {enable_thinking: false} -> the template-level switch
     (recorded fail-soft if this build rejects the field)

Detection mirrors the OV probe (</think> tag + leading-narration heuristic),
extended for llama-server's reasoning-format handling: `message.content` AND
`message.reasoning_content` are captured per condition — thinking that the
server PARSES OUT still counts as thinking GENERATED (the #3937 question is
whether the toggle stops generation, not whether the server hides it).

Usage (box lean, BlarAI down, no other GPU work):
  .venv\\Scripts\\python.exe scripts\\probe_thinking_toggle_llamaserver.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.perf_env_capture import capture_box_state  # noqa: E402

BASE = Path("C:/Users/mrbla/models/gguf-769")
SERVER = BASE / "llamacpp-vulkan" / "llama-server.exe"
PORT = 8089
URL = f"http://127.0.0.1:{PORT}"

MODELS = [
    ("qwen3.6-35b-a3b (MoE — the #3937/#36270 model)", BASE / "Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"),
    ("qwen3.6-27b (dense-hybrid)", BASE / "Qwen3.6-27B-IQ4_NL.gguf"),
]

PROMPT = "How many bytes are in one kilobyte?"  # byte-identical to the OV probe
MAX_TOKENS = 220


def classify(text: str) -> dict[str, Any]:
    """Byte-identical heuristics to the OV probe (comparability)."""
    has_close = "</think>" in text
    lead = text.strip()[:80].lower()
    narration = any(
        s in lead
        for s in ("thinking process", "let me think", "the user is asking", "step 1")
    )
    return {
        "thinking_detected": has_close or narration,
        "has_close_think_tag": has_close,
        "leading_narration": narration,
        "first_200": text.strip()[:200],
    }


def _post_chat(body: dict[str, Any], timeout: float = 600.0) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{URL}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wait_health(deadline_s: float = 240.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=3) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(3)
    return False


def probe_condition(label: str, body: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        resp = _post_chat(body)
    except Exception as exc:  # noqa: BLE001 — a rejected field is itself a datum
        return {"label": label, "error": str(exc)[:300]}
    msg = resp.get("choices", [{}])[0].get("message", {})
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    combined = (reasoning + "\n" + content) if reasoning else content
    out = classify(combined)
    out.update(
        {
            "label": label,
            "seconds": round(time.perf_counter() - t0, 1),
            "reasoning_content_present": bool(reasoning),
            "reasoning_content_first_120": reasoning.strip()[:120],
            "content_first_120": content.strip()[:120],
            "completion_tokens": resp.get("usage", {}).get("completion_tokens"),
        }
    )
    return out


def main() -> int:
    results: dict[str, Any] = {
        "ticket": "#769 item 3 (feeds genai #3937)",
        "probe": "thinking_toggle_llamaserver",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "llamacpp_build": "b9957 official win-vulkan-x64 release",
        "server_args": "-ngl 99, default reasoning handling (introspected per response)",
        "prompt": PROMPT,
        "max_tokens": MAX_TOKENS,
        "environment": {"box_state_at_start": capture_box_state()},
        "models": {},
    }

    for model_label, gguf in MODELS:
        if not gguf.exists():
            results["models"][model_label] = {"error": f"missing {gguf}"}
            continue
        print(f"=== {model_label}: starting llama-server…", flush=True)
        # stderr goes to a FILE, never a PIPE: llama-server logs every request
        # to stderr and an undrained pipe deadlocks the server once the buffer
        # fills. The file doubles as the Lesson-151 layer-offload evidence.
        stderr_path = BASE / "results" / f"server_{gguf.stem}.log"
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_file = open(stderr_path, "w", encoding="utf-8", errors="replace")
        # BOTH streams to the file — this build logs load/offload to stdout.
        proc = subprocess.Popen(
            [str(SERVER), "-m", str(gguf), "-ngl", "99", "--host", "127.0.0.1",
             "--port", str(PORT), "-v"],
            cwd=str(SERVER.parent),
            stdout=stderr_file,
            stderr=subprocess.STDOUT,
        )
        model_res: dict[str, Any] = {"gguf": gguf.name, "server_log": str(stderr_path)}
        try:
            if not _wait_health():
                stderr_file.flush()
                tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-500:]
                model_res["error"] = f"server never became healthy; stderr tail: {tail}"
                continue
            offload = [
                ln for ln in stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if "offload" in ln.lower()
            ]
            model_res["offload_evidence"] = offload[-3:]
            print(f"  offload: {offload[-1] if offload else 'NOT FOUND in server log'}", flush=True)
            base_msgs = [{"role": "user", "content": PROMPT}]
            nothink_msgs = [{"role": "user", "content": PROMPT + " /no_think"}]
            model_res["conditions"] = {
                "A_plain": probe_condition(
                    "A plain",
                    {"messages": base_msgs, "max_tokens": MAX_TOKENS, "temperature": 0},
                ),
                "B_no_think_switch": probe_condition(
                    "B /no_think",
                    {"messages": nothink_msgs, "max_tokens": MAX_TOKENS, "temperature": 0},
                ),
                "C_enable_thinking_false": probe_condition(
                    "C chat_template_kwargs enable_thinking=false",
                    {
                        "messages": base_msgs,
                        "max_tokens": MAX_TOKENS,
                        "temperature": 0,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                ),
            }
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
            stderr_file.close()
            results["models"][model_label] = model_res
            time.sleep(8)
        for cond, res in model_res.get("conditions", {}).items():
            print(f"  {cond}: thinking={res.get('thinking_detected')} "
                  f"reasoning_field={res.get('reasoning_content_present')} "
                  f"err={res.get('error', '')[:80]}", flush=True)

    out_dir = _REPO_ROOT / "docs" / "performance"
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_dir / f"probe_thinking_toggle_llamaserver_{stamp}.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"results: {out_path}")
    ok = any("conditions" in m for m in results["models"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
