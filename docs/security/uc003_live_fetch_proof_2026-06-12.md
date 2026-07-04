# UC-003 Live-Fetch Proof — the first sanctioned external egress (#655)

**Date:** 2026-06-12 (LA present, screen live, LA-directed go-live test).
**Result:** GREEN — BlarAI fetched a real internet article through the one
Policy-Agent-gated door, parsed the hostile HTML inside the NIC-less guest, and
composed a clean preview, end to end. **This is the air-gap-removal moment,
proven on the real machine.**

## What ran

Harness: `scripts/uc003_live_fetch_smoke.py`, run under the 3.11 runtime venv
(`C:/Users/mrbla/blarai/.venv`). The guest parse hop ran through the production
version bridge (a py-3.14 subprocess — the 3.11 runtime lacks `socket.AF_HYPERV`),
exactly the production architecture.

Sequence (all on the real box):
1. Booted the NIC-less guest (`Start-VM BlarAI-Orchestrator`) — **VmId
   `9c7f986f-7afd-48b0-af5b-2c330df6b38f`, NIC count 0** (zero-NIC posture intact),
   2 GB. The resident `blarai-parser` OpenRC service auto-started on boot.
2. Health-checked the parser via the proven AF_HYPERV smoke (`guest_parser_smoke.py`)
   — PASS, **zero network touched** (fixed in-script HTML).
3. Brought the guest parser to READY via the bridge (resident model — no deploy).
4. Registered the deterministic PA adjudicator with **exactly one host
   allowlisted** — `www.bleepingcomputer.com` — for this one fetch (the ADR-027
   Amendment 1 per-action carve-out: "the paste is the consent for that ONE URL").
5. **First sanctioned egress** through `shared.security.guarded_fetch.fetch_external`.

## The green signal (verbatim)

- **Fetch:** `GET https://www.bleepingcomputer.com/news/security/github-announces-npm-security-changes-to-tackle-supply-chain-attacks/`
  → **HTTP 200**, `content_type='text/html; charset=UTF-8'`, **89,219 bytes**,
  `injection_flags=[]`. The door logged the per-fetch allowlist WIDEN for
  `www.bleepingcomputer.com:443` and the guaranteed REVOKE after.
- **Guest parse** (inside the NIC-less VM, over AF_HYPERV vsock): `status=clean`,
  `word_count=450`.
- **Host-composed verdict** (`clean_from_guest_parse`, ADR-030 §5 injection axis):
  - title: `'GitHub announces npm security changes to tackle supply-chain attacks'`
  - byline: `'Bill Toulas'`
  - published: `'2026-06-10'`
  - word_count: `450`
  - **status: `clean`**, confidence `1.000`, reasons `[]`
  - cleaner_version `1.0.0`, source_format `html`
  - cleaned-text preview opened: *"GitHub has announced that npm v12, expected
    next month, will introduce several security-focused changes aimed at blocking
    supply-chain attacks abusing behaviors triggered by the 'npm install'
    command…"* — accurate article text, chrome stripped.

## Re-weld (fail-closed return to dormant)

The harness cleared the PA adjudicator and stopped the parser in a `finally`
(`PA adjudicator CLEARED + parser stopped — egress door back to deny-by-default`),
and the process exited (in-process registration is gone by construction). The VM
was then stopped (`Stop-VM` → **State Off**). The runtime is back to its dormant
at-rest state: door welded by all three locks (no adjudicator registered,
`guest_parser.enabled=false`, empty egress allowlist), VM off.

## Scope / what was NOT exercised (named honestly)

- **`egress_guard` was NOT globally armed** for this first shot: the door's
  pre-fetch SSRF resolution would trip an armed guard before the per-fetch widen
  (documented in `guarded_fetch`). The rule-3 kill-switch layer is covered by
  `tests/security`; the armed-posture live run is a clean follow-up.
- **Parse-channel mTLS stayed dormant** (plaintext on-box AF_HYPERV vsock — never
  a network path). The named hard gate for the *production* posture; activation is
  a guest cert re-provision (host-side plumbing already in place, `eb30cf9`).
- This is the host-side smoke harness, not the operator's WinUI `/ingest` surface;
  it drives the identical production components (`guarded_fetch` →
  `GuestParserManager.parse_html` → `clean_from_guest_parse`).
