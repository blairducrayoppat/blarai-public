# web_search Go-Live Runbook

**Allowlist → tripwire re-baseline → key → flag → boot → one benign query →
full-chain verify → evidence.** ADR-024 (W4) + ADR-027 §2/Am.1. For the Lead
Architect (non-developer-friendly). This is the SEPARATE, LA-present ceremony
that takes the model-callable `web_search` tool from DORMANT to live — the
first LIVE Kagi query is the go-live moment. Everything below Step 1 is
reversible; Step 6's first outbound GET is the point of no return for that one
request.

> **What this ceremony makes live:** the 14B can call `web_search` and get real
> Kagi results, fetched through the ONE egress door
> (`shared/security/guarded_fetch.py`) with the URL adjudicated by the
> deterministic Policy-Agent rules at TWO layers (the tool loop's D4 dispatch
> check AND the door itself — both reading the SAME single allowlist), results
> grounded as **UNTRUSTED_EXTERNAL** (datamarked, Layer-3 action-locking,
> Stage-5 leakage-screened). It does NOT light up UC-003 URL ingest, images, or
> any other egress consumer — those have their own ceremonies and their own
> locks.

## What is ALREADY BUILT (the #719 Part B build — verify, don't build)

- `shared/secrets/kagi_key_loader.py` — boot-time key loader over the
  DPAPI-sealed blob; returns the key WRAPPED (redacted in every log/repr);
  absent/empty/malformed → dormant.
- `services/assistant_orchestrator/src/websearch/live_adapter.py` — the
  `LiveKagiAdapter` (ADR-024 W4): fetches ONLY via
  `guarded_fetch.fetch_external` (`POST /api/v1/search`, `Authorization:
  Bearer <key>`, JSON body `{"query": ...}`), parses the v1 `data.search`
  results defensively, shapes deterministic title/url/snippet results (HTML
  tags stripped), fail-closed to the deterministic failure notice on ANY error.
- Conditional registration in the AO entrypoint
  (`_maybe_register_web_search`): the runner registers at boot ONLY when
  `[web_search].enabled = true` AND the key loads. Also wires the egress
  door's deterministic URL adjudicator if none is registered.
- **D4** (LA decision, #719 c.1298): the tool loop's #570 dispatch CAR for
  `web_search` carries the REAL endpoint URL, so RULE 3 + the deterministic
  egress allowlist govern the loop as well as the door — ONE allowlist source
  (`DeterministicPolicyChecker._EGRESS_ALLOWLIST`), no second list.
- Eval locks: `gov-pf-007` (the endpoint is RULE-3-DENIED while the allowlist
  is empty — the go-live tripwire THIS ceremony flips) and `gov-adj-008` (the
  loop-level D4 denial while dormant).

## Preconditions (verify BEFORE starting)

1. The standing gate and the eval gate are green on current `main`
   (`.venv/Scripts/python.exe -m evals.run --suite all` → exit 0).
2. `[web_search].enabled = false` in
   `services/assistant_orchestrator/config/default.toml` (the shipped
   default) and no Kagi key blob exists yet at
   `%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi` (fresh box) — or an
   existing blob is the one you intend to use.
3. A funded Kagi account with Search API access (the API is billed per
   search; the key is created at kagi.com → Settings → Advanced → API portal).
4. **ENDPOINT VERSION — RESOLVED at #724 (2026-07-02):** the build targets the
   **v1** endpoint (`POST https://kagi.com/api/v1/search`, `Authorization:
   Bearer <key>`, JSON body `{"query": ...}`, results under `data.search`).
   The original build pinned **v0** (`GET /api/v0/search`, `Bot` header, flat
   `data`-array) against the then-current ADR-024 / help.kagi.com docs; the
   first live fetch at this ceremony returned **HTTP 401**, and probing the
   real key proved v0 is deprecated and v1/POST/Bearer/JSON-body is the live
   contract. `KAGI_SEARCH_ENDPOINT` (live_adapter.py), the `_AUTH_SCHEME`
   (`Bearer`), the v1 `data.search` parser, and the `gov-pf-007` / `gov-adj-008`
   golden resources all moved together (a coupling test fails if they fork).
   No decision remains here — the four axes are already corrected.

> **INTERPRETER — run every Python command below with the project venv, NOT the
> bare `python`:** `C:/Users/mrbla/blarai/.venv/Scripts/python.exe`.
> **Run every command from the repo root `C:\Users\mrbla\blarai`.**

## Step 1 — Populate the egress allowlist (THE governance act, ADR-027 Am.1)

This is the single act that opens BOTH layers (the D4 tool-loop check and the
egress door read the same list). It is a **reviewed code change on a feature
branch**, never a live-tree edit:

1. In `services/policy_agent/src/gpu_inference.py`, set the checker's
   allowlist to exactly the one host the feature needs:

   ```python
   _EGRESS_ALLOWLIST: ClassVar[frozenset[str]] = frozenset({"kagi.com"})
   ```

   (Lowercase host only — no scheme, no port, no path. `kagi.com` and nothing
   else: ADR-027 §1, "the allowlist names web endpoints a feature needs".)
2. In the SAME change, record the decision: a `docs/DECISION_REGISTER.md` row
   naming ADR-027 Amendment 1 activation for `kagi.com` (web_search go-live),
   the date, and this runbook as the procedure.
3. In the SAME change, do Step 2 (the tripwire re-baseline) — the gate will
   not pass otherwise, which is the tripwire doing its job.

## Step 2 — gov-pf-007 reviewed baseline refresh (the tripwire flip)

`evals/golden/governance.jsonl` case `gov-pf-007` pins: *the Kagi endpoint is
DENIED by RULE 3 while the allowlist is empty*. Step 1 flips its outcome to
ALLOW (`expected: null`) — update the case's `expected` and description to pin
the NEW posture (allowlisted host auto-approved, logged, exfil-screen applies
at send), and name the old→new verdict in the commit message. Case
`gov-adj-008` (the D4 loop-level denial) flips identically — update it in the
same commit. Run the eval gate and the standing gate; both must be green
before merge. Merge the branch per normal review.

## Step 3 — Key placement (LA, at the keyboard — the key never touches chat, logs, or git)

1. Create/copy the API key from the Kagi API portal **directly into the
   provisioning prompt** — do not paste it into a chat window, a note, or a
   file (no Notepad staging: the ceremony script reads it with echo disabled
   and seals it straight into DPAPI).
2. Run the provisioning ceremony:

   ```powershell
   C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m shared.secrets.provision_kagi_key
   ```

   Type (or paste) the key at the hidden prompt. Expect
   `round-trip : PASS` and the blob path
   `%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi`.
3. Verify the loader accepts it WITHOUT printing it:

   ```powershell
   C:/Users/mrbla/blarai/.venv/Scripts/python.exe -c "from shared.secrets.kagi_key_loader import load_wrapped_kagi_key; k = load_wrapped_kagi_key(); print('LOADED (redacted):', k)"
   ```

   Expect `LOADED (redacted): KagiApiKey(<redacted>)`. A `None` means the
   blob is absent/malformed — re-run the provisioning step.
   (Rotation later = re-run the same provisioning command; the blob is
   overwritten. See `docs/runbooks/kagi_key_provisioning.md`.)

## Step 4 — Flip the flag

In `services/assistant_orchestrator/config/default.toml`:

```toml
[web_search]
enabled = true
```

Commit on the ceremony branch (or as the LA's recorded live-config change,
matching how `[image_generation].enabled` was flipped at the UC-010 ceremony).

## Step 5 — Boot and verify the registration banner

Start BlarAI normally. In `launcher.log` expect, in order:

- NO line containing the key value (spot-check: search the log for the first
  4 characters of the key — it must NOT appear anywhere);
- `web_search runner REGISTERED (flag on + key loaded).` —
  the conditional registration fired;
- `guarded_fetch: per-URL Policy-Agent adjudicator registered` — the door has
  its deterministic adjudicator.

If instead you see `no usable Kagi API key is provisioned` → Step 3 failed;
stop and re-provision. If you see nothing → the flag did not resolve; check
Step 4.

## Step 6 — One benign query (explicit LA GO — the first live GET)

With the LA watching the screen and the log, say GO, then ask BlarAI something
benign and current that its local knowledge cannot answer, e.g.:

> What is the latest OpenVINO release?

The model should choose `web_search`. **This fires the first live outbound GET
to kagi.com.** Expect a grounded answer citing the shaped results.

## Step 7 — Full-chain live-verify checklist (tick every line in the log)

1. **PA loop adjudication (D4):** NO `Tool call 'web_search' refused by
   Policy Agent` line — the allowlisted dispatch passed the loop check, and
   the PA egress carve-out line `PA egress carve-out (ADR-027 §2):
   auto-APPROVED allowlisted egress host=kagi.com` appears (it fires at the
   loop AND at the door — two occurrences per search are correct).
2. **The door:** `guarded_fetch: WIDEN egress allowlist for one fetch —
   host='kagi.com' port=443` followed by the matching `REVOKE` line (the
   widen is always narrowed back).
3. **Kagi answered:** the reply carries real result titles/URLs; no
   `Web search failed` notice.
4. **UNTRUSTED_EXTERNAL grounding:** the tool note in the reply context says
   the results were *added to the grounded context* (not `Result: ...`
   spliced raw); a follow-up `/status`-style check (or the session behavior
   below) confirms untrusted provenance is present.
5. **Layer-3 lock behavior:** in the SAME session, ask BlarAI to do something
   needing a GUARDED tool (e.g. another web search). Expect the Layer-3
   refusal naming `/trust` — web content locked the session's non-SAFE tools
   exactly as designed. `/trust`, repeat, and it proceeds.
6. **Key hygiene re-check:** search `launcher.log` for the key's first 4
   characters again — zero hits.

If ANY line fails: go to the re-weld procedure below, then investigate on a
branch.

## Step 8 — Evidence + record (same day)

- `PERFORMANCE_LOG.md`: a dated entry — first live web_search turn latency,
  result count, and the hardware/driver/model context (community-grade,
  name what was NOT measured).
- `BUILD_JOURNAL.md` (or a fragment if the tree is contended): the go-live
  narrative — the ceremony as run, anything that surprised.
- Vikunja #719: comment with the GO, the verify checklist outcome, and the
  commit SHAs (allowlist change + baseline refresh + flag flip).
- `docs/DECISION_REGISTER.md` row (landed with Step 1's change — confirm it
  merged).

## Re-weld procedure (if anything surprises)

Any ONE of these restores dormancy; do them in this order until comfortable:

1. **Flag off:** `[web_search].enabled = false` + restart — the runner never
   registers; web_search returns its deterministic unavailable notice.
2. **Allowlist empty:** revert the Step-1 commit (restore
   `frozenset()` + restore the gov-pf-007/gov-adj-008 baselines in the same
   revert) — RULE 3 denies every dispatch at the loop AND every URL at the
   door, even if the flag/key remain.
3. **Key removal (strongest):** delete
   `%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi` (and rotate the key at
   the Kagi portal if compromise is suspected) — the loader fail-closes and
   registration never fires.

Each is independently sufficient; together they restore the shipped
triple-lock. Record the re-weld and its reason on #719.

## Out of scope (separate events)

- UC-003 `/ingest <url>` text go-live (its own runbook + adjudicator wiring —
  note both go-lives share the door's SINGLE adjudicator slot: whichever
  ceremony runs second must verify the registered adjudicator serves both
  postures, and the operator "paste = consent" factory vs the standing
  allowlist is an LA call at that point).
- Display-only images (BED-1 purpose-deny + `[knowledge].images_enabled`).
- `summarize_url` / the W3 agentic multi-step search loop (W5 defenses not
  yet live — the shipped runner is single-shot search + grounded results).
- Any v0→v1 endpoint migration (Precondition 4) if not done before this
  ceremony.
