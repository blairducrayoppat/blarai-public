#!/usr/bin/env python
"""Replace the agent-generated mermaid (which used literal \\n + unquoted special
chars -> parse errors) with hand-authored, conservative, valid mermaid, then lint
it mechanically. Re-run build_deck.py afterwards.
"""
import json
import pathlib
import re

D = pathlib.Path(__file__).resolve().parent
deck = json.loads((D / "deck_outline.json").read_text(encoding="utf-8"))

ARCH = """flowchart TD
  USER["You: prompts + documents"] --> WINUI["WinUI window<br/>Medium integrity (ADR-019)"]
  WINUI -->|"named pipe (local only)"| BACKEND["UI backend / dispatcher"]
  BACKEND --> GW["Transport Gateway"]
  GW -->|"HOST default: loopback TCP, NO mTLS"| AO["Assistant Orchestrator"]
  AO --> MODEL["Qwen3-14B on Arc 140V GPU"]
  AO --> PGOV["PGOV output validator (6 stages)"]
  AO --> SUB[("substrate.db<br/>full docs + every turn<br/>PLAINTEXT")]
  BACKEND --> SESS[("sessions.db<br/>PLAINTEXT")]
  AO -->|"adjudication (HOST default: NO mTLS)"| PA["Policy Agent<br/>authorization choke-point"]
  PA -->|"signs with"| PEM["pa_private.pem<br/>CLEARTEXT, IN GIT"]
  PA --> MAN["manifest.json<br/>UNSIGNED, 342 bytes"]
  subgraph VM["Hyper-V Alpine VM (started but EMPTY)"]
    EMPTY["no PA / AO runs here today"]
  end
  LAUNCH["Launcher (UAC-elevated)"] -.->|"Start-VM only"| VM
  subgraph UNWIRED["Built but wired into nothing"]
    TPM["TPM 2.0 non-exportable key<br/>0 production callers"]
  end
  TPM -.->|"should seal key + sign manifest"| PEM
  AIRGAP["AIR-GAP: the real defense today"] --- LAUNCH"""

TRUST = """flowchart LR
  subgraph OUTSIDE["Outside world (today: empty, air-gapped)"]
    WEB["Future: web pages, retrieval, internet"]
  end
  subgraph MACHINE["The single Lunar Lake machine"]
    subgraph TRUSTED["Same-user trust zone (one elevated process)"]
      AO2["Assistant Orchestrator"]
      PA2["Policy Agent"]
      DBS[("Plaintext DBs + cleartext key + deletable logs")]
    end
    DEVSESS["Claude DEV session<br/>full internet + arbitrary exec<br/>same disk, same key, same DBs"]
  end
  WEB -.->|"air-gap removed = this becomes live"| TRUSTED
  DEVSESS --- TRUSTED
  OUTSIDE -.->|"blocked only by absence of network, not by code"| MACHINE"""

FLOW = """flowchart TD
  REQ["Agent action request"] --> CN{"Caller identity bound to request?"}
  CN -->|"HOST / guest dev_mode: SKIPPED"| RULES["Deterministic rule engine<br/>structural / sensitivity / ACL / rate / resource"]
  CN -->|"production mTLS: CN must match"| RULES
  RULES -->|"any DENY = final"| DENY["DENY (no token)"]
  RULES -->|"pass"| REHASH["Re-hash full multi-GB model every request"]
  REHASH -->|"mismatch"| DENY
  REHASH -->|"ok"| PREFILT["Deterministic deny-list pre-filter"]
  PREFILT -->|"DENY rule"| DENY
  PREFILT -->|"ESCALATE rule"| ESC["ESCALATE (no consumer = silent DENY)"]
  PREFILT -->|"clear"| LLM["LLM classifier"]
  LLM --> CONF{"confidence at least 0.75?"}
  CONF -->|"model never emits confidence; ALLOW defaults to 0.0"| ESC
  CONF -->|"effectively unreachable"| ALLOW["ALLOW"]
  ALLOW --> MINT["Mint ES256 token (nonce, jti, epoch, 30s TTL)"]
  MINT -->|"signs with cleartext key in git"| KEY["pa_private.pem"]
  MINT --> TOKEN["Authorization token to caller"]"""

ATTACK = """flowchart TD
  WEB["Hostile web page / retrieved doc"] -->|"injection; Cleaner absent"| INJ["Prompt injection reaches model"]
  INJ -->|"tool-gate DISABLED, /trust broken"| ACT["Model takes an action"]
  INJ -->|"leakage check fed empty list"| LEAK["Secrets echoed into reply, unfiltered"]
  FOOT["Any online foothold"] --> DBREAD["Read substrate.db: full history, cleartext"]
  FOOT --> KEYREAD["Read pa_private.pem: forge ALLOW tokens"]
  KEYREAD --> BYPASS["Defeat the authorization choke-point"]
  FOOT --> ERASE["Erase plaintext logs: no forensic trace"]
  SUPPLY["Compromised dependency"] --> EXFIL["Exfiltrate via already-loaded network libs (once air-gap off)"]
  AIRGAP["Air-gap blocks WEB + foothold start points TODAY"] -.-> WEB
  AIRGAP -.-> FOOT"""

sd = deck["system_diagrams"]
sd[0]["mermaid"], sd[1]["mermaid"], sd[2]["mermaid"] = ARCH, TRUST, FLOW
for s in deck["slides"]:
    if s.get("mermaid"):
        s["mermaid"] = ATTACK if "ttack" in s.get("title", "") else ""  # null redundant inline
(D / "deck_outline.json").write_text(json.dumps(deck, indent=2), encoding="utf-8")

# Mechanical lint of the replaced diagrams.
items = [("sys:" + sd[i]["title"][:34], sd[i]["mermaid"]) for i in range(len(sd))]
items += [("slide:" + s["title"][:34], s["mermaid"]) for s in deck["slides"] if s.get("mermaid")]
ok = True
for name, code in items:
    errs = []
    if "\\n" in code:
        errs.append("literal-\\n")
    sg = len(re.findall(r"\bsubgraph\b", code))
    en = len(re.findall(r"^\s*end\s*$", code, re.M))
    if sg != en:
        errs.append(f"subgraph/end={sg}/{en}")
    for op, cl, nm in [("[", "]", "[]"), ("(", ")", "()"), ("{", "}", "{}")]:
        if code.count(op) != code.count(cl):
            errs.append(nm)
    # every node/edge label should be quoted: flag a bare [word with a stray special char
    print(("OK   " if not errs else "FAIL ") + name + ("" if not errs else " -> " + ",".join(errs)))
    ok = ok and not errs
print("LINT:", "PASS" if ok else "FAIL")
