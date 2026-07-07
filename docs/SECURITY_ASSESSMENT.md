# BlarAI Security Assessment — Validated Findings

**Date:** 2026-03-05  
**Scope:** Policy Agent, IPC layer, shared schemas, crypto, rule engine  
**Method:** Automated subagent audit + manual cross-referencing against actual code

---

I audited the security-relevant code across the Policy Agent, IPC layer, shared schemas, crypto, and rule engine. Here's what's real after cross-referencing the subagent's findings against actual code.

---

## CRITICAL — `source_agent` Identity Not Verified Against mTLS Certificate CN

**The single most important security gap in the system.**

The architecture documents and code comments consistently state that `source_agent` corresponds to the mTLS Common Name. The mTLS infrastructure exists — `vsock.py:101` sets `verify_mode = ssl.CERT_REQUIRED`, TLS 1.2+ is enforced, mutual cert auth is mandatory in production. However, **nowhere in the codebase does any code call `getpeercert()` to extract the CN and validate it against `car.source_agent`**.

This means a compromised agent that holds a valid client cert (say, with CN="coder") can forge CARs claiming `source_agent="assistant_orchestrator"` and bypass any ACL or deterministic rule that keys on agent identity. The new `ESCALATE_CROSS_AGENT_OWNERSHIP` rule (Task 4.9d) specifically trusts `source_agent` to detect ownership mismatches — this rule is defeated if `source_agent` is spoofable.

**Fix:** Extract the peer cert CN after TLS handshake in `VsockListener.accept()` or `PolicyAgentListener.handle_connection()` and propagate it alongside the raw message. Before adjudication, compare `car.source_agent == peer_cn`. Fail-Closed DENY on mismatch.

---

## CRITICAL — `parameters_schema` Injected Directly Into LLM Prompt

At `gpu_inference.py:193`, `car.parameters_schema` is serialized via `json.dumps()` and concatenated directly into the user message sent to the LLM.

There is **no schema validation, no sanitization, and no allowlist of keys**. An attacker crafting a malicious CAR can embed prompt injection payloads inside `parameters_schema` that the LLM will parse as instructions. The deterministic pre-filter checks `parameters_schema` for `/tmp/export/` and authority claim patterns, but those are narrow string matches — they don't catch general prompt injection.

**Fix (two-prong):**

1. Validate that `parameters_schema` conforms to JSON Schema vocabulary (only allow `type`, `properties`, `required`, `items`, `description`, `enum`, `default`, etc.). Reject unknown keys.
2. As defense-in-depth, escape or boundary-delimit the serialized parameters in the prompt (e.g., wrap in explicit delimiters the system prompt instructs the model to treat as untrusted data).

---

## HIGH — Authority Claim Regex Has Bypass Gaps

The `_AUTHORITY_CLAIM_RE` at `gpu_inference.py:254` is limited to 5 specific patterns. Unicode homoglyphs (U+2011 non-breaking hyphen instead of `-`), tokenization-aware word splits ("pre approved" with a space), or synonym substitution ("admin cleared", "management authorized") bypass the regex entirely. Since this rule is a defense-in-depth DENY trigger against social engineering in `parameters_schema`, its bypass directly enables the prompt injection vector above.

**Fix:** Add Unicode normalization (`unicodedata.normalize("NFKD", ...)`) before pattern matching, and expand the pattern set. Consider a dedicated deny-word list rather than a single regex.

---

## MEDIUM — `sensitivity` Defaults to `UNCLASSIFIED` (Fail-Closed by Design, but Noisy)

At `car.py:94`, `sensitivity` defaults to `Sensitivity.UNCLASSIFIED`, and the rule engine correctly DENY-blocks UNCLASSIFIED CARs. This is fail-closed and safe — but it means that if a caller forgets to set `sensitivity`, the request is silently denied with no clear error indication to the caller about *why*. Making `sensitivity` a required field (no default) would catch integration bugs at CAR construction time rather than at adjudication time.

---

## MEDIUM — Confidence Parser Fails Open to 0.995

At `gpu_inference.py:87`, when the confidence regex doesn't match, `_DEFAULT_LABEL_CONFIDENCE` returns 0.995 for any label. This means an LLM output with a garbled or missing confidence value gets treated as high-confidence. If the system ever adds a confidence threshold gate (e.g., "ALLOW only if confidence > 0.9"), this fail-to-high-confidence behavior would bypass it.

Currently no threshold gate exists in production, so this is **latent risk** — but worth noting for Task 5 and beyond.

---

## LOW — JWT NonceStore Uses `time.time()` Instead of `time.monotonic()`

Confirmed at `jwt_validator.py:80`. If the system clock jumps backward (NTP correction, manual change), nonces could persist past their intended TTL. The rate limiter in `rule_engine.py:119` already correctly uses `time.monotonic()` — the NonceStore should match.

---

## LOW — Config Path Resolution Doesn't Check Symlinks

`runtime_config.py` resolves config paths without verifying they aren't symlinks. Requires local filesystem write access to exploit — low probability on a single-user system, but trivial to add `resolved.is_symlink()` check.

---

## FALSE POSITIVE — Rate Limiter Threading (DISMISSED)

The subagent flagged the rate limiter as not thread-safe. Verified: the `serve_forever()` loop in `ipc.py` is genuinely sequential — accept, handle, close, repeat. No concurrent request processing. The documented single-threaded design is architecturally enforced. Not a real issue.

---

## Summary — Priority Order

| Priority | Finding | Effort |
|----------|---------|--------|
| **P0** | mTLS CN → `source_agent` validation | Task 4.11 |
| **P0** | `parameters_schema` JSON Schema validation + prompt injection defense | Task 4.11 |
| **P1** | Authority claim regex expansion + Unicode normalization | Task 4.11 |
| **P1** | `sensitivity` field: remove default, make required | Task 4.11 (API-breaking) |
| **P2** | NonceStore → `time.monotonic()` | Task 4.11 |
| **P2** | Config symlink check | Task 4.11 |
| **P2** | Confidence fallback → fail-closed instead of 0.995 | Task 4.11 |

The two P0 items — **mTLS CN validation** and **`parameters_schema` sanitization** — are scoped as **Task 4.11** (pre-Task-5 security hardening). The mTLS CN gap is particularly important because the ESCALATE rules added in Task 4.9d explicitly depend on `source_agent` integrity. Task 5 (model upgrade to Qwen3-14B) is blocked on Task 4.11 completion.
