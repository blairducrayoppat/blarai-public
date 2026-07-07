# ADR-032 — UC-003 Workstream B: Display-Only Images

**Status:** ACCEPTED 2026-06-14 (Lead-Architect-ratified at the #663 Workstream B comprehension gate;
the image-host consent posture decided on #663 c.1088). Built DORMANT — no live image fetch ships.
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-027 (Egress Policy — the one PA-gated door this adds a binary sibling to),
ADR-030 (UC-003 Cleaner v1 — the guest-homed ingest pipeline whose extraction this extends),
ADR-031 (Substrate v2 Knowledge Bank — the encrypted store the new `knowledge_images` table joins,
under the same ADR-025 DEK/field-cipher/AAD posture), ADR-013 (the Layer-1/2 defenses the alt-text
escape re-enters), ADR-029 (the audit chain the #663-A edit provenance rides).
**Relates to:** Vikunja #663 (UC-003 ingest review v2), #659 (egress go-live — NOT folded into it),
#662 (the CD-ISO guest re-provision channel), `Use Cases_FINAL.md` §003.

## Context

UC-003 ingests web articles into the knowledge bank. Workstream A (#663-A) made the preview editable.
Workstream B adds the article's **content images** to that already-curatable preview. The binding
operator need is fidelity (an article without its diagrams is degraded); the binding constraint is
that web image bytes are **untrusted, attacker-controlled input** entering a security-first, air-gap-
removal-pending system. The naive shapes are both wrong: re-fetching images at render time creates a
permanent external dependency and a phone-home vector; feeding image pixels to the vision model treats
hostile bytes as a trusted modality. This ADR records the posture that lets images in without either.

Three facts shaped the design, each verified on disk before building: (1) the text staging file and
the host↔guest parse channel are text-only, so image bytes need their own transport; (2) trafilatura
does **not** escape image alt-text, so `![x](javascript:…)` is a live markdown-injection vector the
cleaner's phrase scanner misses; (3) the embedder and the knowledge store only ever receive `str`, so
a structural no-VLM guarantee is enforceable, not merely promised.

## Decision

1. **Snapshot once, never re-fetch (no external dependency).** Image bytes are fetched a single time
   at ingest and stored encrypted locally; the article may vanish afterward. The stored document never
   carries a remote image URL — every `![alt](url)` is rewritten to a local `blarai-img://<id>` ref or
   dropped to an inert `[image: alt]` placeholder. The renderer resolves `blarai-img://` from decrypted
   local bytes and never touches the network.

2. **Display-only — NO embedding, NO VLM on image pixels, ever.** Image bytes are stored for inline
   render only; they are never chunked, embedded, indexed, or sent to any model. This is deliberate
   hardening (keep the vision model off untrusted web pixels), enforced structurally by a fail-closed
   type assertion at both `_embed` call sites (`embed() received non-string` raises) and by `retrieve()`
   never querying `knowledge_images`. The VLM's existing `describe_image` path (operator-attached
   images) is separate and untouched.

3. **Binary egress door as a SIBLING, not a second door.** A new `fetch_external_binary` +
   `BinaryFetchResult` shares the one PA-gated door's pipeline (SSRF guard → PA adjudication →
   resolution recheck → the shared `_fetch_raw` transport with the always-runs allowlist revoke);
   the frozen text `FetchResult` contract is untouched. The text injection scan is replaced for binary
   by a content-type allowlist (png/jpeg/gif/webp), a **required magic-byte sniff** (refuse header/body
   mismatch), and SVG refusal. Danger is the technical controls' job.

4. **Image-host consent is COARSE and about egress/privacy only** (#663 c.1088). A hostname is not
   something a human can judge for *safety* — danger is decision 3's job. Consent governs only what the
   box may reach: images on the article's **own host** load under the existing article-ingest consent;
   if the article references images on **other hosts**, the operator gives **one yes/no for the whole
   article**, with the distinct other-hosts shown for disclosure, never as a per-host vetting chore.
   This rejects the earlier "show the host list and vet each" framing as a rubber-stamp trap.
   **(Amendment 2, 2026-06-15: IMPLEMENTED coordinator-side — the same-site/off-site host classifier
   (exact-host grain) + the fail-closed off-site consent seam (`shared.security.image_egress_consent`);
   the WinUI per-article yes/no prompt is Pass B. Also LA-locked there: paste/file ingests fetch NO
   remote images at all — only a URL-ingested article does.)**

5. **Ship DORMANT behind a fourth, independent weld lock.** The image path stays closed by
   `[knowledge].images_enabled=false` (new, default false) **in addition to** the three existing egress
   weld locks (`guest_parser.enabled=false`, no registered URL adjudicator, empty deterministic egress
   allowlist). Any one lock closed ⇒ no image is fetched or stored. (Amendment 1 / BED-1 refines the
   "independent" claim: two of these locks — the registered URL adjudicator and the deterministic egress
   allowlist — are SHARED with the text door and release at text URL-ingest go-live; the image path's
   go-live-independent locks are the image-purpose-deny added in BED-1 + `images_enabled`.) The corridor *logic* is built across
   every layer (door, transport, storage, cleaner, coordinator, AO, WinUI) so it is not a design stub —
   but it is NOT a single-flip activation: the gateway constructs the coordinator with `images_enabled`
   defaulting false and does not yet read the flag from config (a named go-live residual), so enabling
   images is the full go-live ceremony, not one config toggle. Going live is a separate LA-present
   ceremony with its own egress review — explicitly NOT folded into the #659 page go-live — and requires
   wiring the gateway flag + registering the shared PA adjudicator (there is no separate "binary
   adjudicator" — `fetch_external_binary` rides the SAME one as the text door) + lifting the image
   purpose-deny + flipping `[knowledge].images_enabled` + a #662 CD-ISO guest re-provision for
   `include_images`.

## Consequences

- A new encrypted `knowledge_images` table (image_id uuid4, doc_uuid FK CASCADE, keyed-hash dedup,
  blob/alt/source_url encrypted under the shared DEK with AAD binding **both** doc_uuid and image_id —
  parity with `image_staging` and `knowledge_chunks`, closing cross-doc replay), and a sibling
  `image_staging` binary handoff. No new runtime dependency.
- The always-on alt-text escape runs on every cleaned document regardless of the image locks (the refs
  live in text the operator reviews today); it must match the WinUI renderer's URL grammar exactly, and
  the renderer additionally allows only http(s) links to navigate (defense in depth).
- Caps bound the blast radius of a hostile article: 20 images/article, 2 MiB/image, 8 MiB total are
  ENFORCED in the corridor. A sub-32px dimension drop is specified (`MIN_IMAGE_DIMENSION_PX=32`)
  — **implemented in Amendment 1 (2026-06-15)**; originally a named residual. The 20 count is an LA
  sanity-check item to confirm before go-live.
- Deferred to go-live (cannot fire while dormant; named, not silent) — **the HEADLESS subset of this
  list was closed in Amendment 1 (2026-06-15); see it for current status**: ~~wiring the gateway
  `images_enabled` flag from config~~ (CLOSED #1); ~~the sub-32px dimension drop~~ (CLOSED #7);
  ~~approve-time promotion / reject-time handling of image rows~~ (CLOSED #3); ~~edit-approve cascade of
  a kept image~~ (CLOSED #2); ~~forged-`blarai-img://` render-id FORMAT validation~~ (CLOSED #4, format
  gate — set-membership remains go-live); ~~binary-door SSRF-recheck/ESCALATE tests~~ (CLOSED #5);
  ~~AO-side MIME re-validation~~ (CLOSED #6). **Still deferred to the LA-present go-live ceremony:** the
  live-pixel WinUI render + on-hardware visual confirm; the #4 set-membership manifest; registering the
  shared PA adjudicator (the same one the text door uses) + lifting the image purpose-deny + populating
  the egress allowlist + the #662 CD-ISO guest re-provision + flipping the flag (the first irreversible
  outbound GET).

## Alternatives rejected

- **Re-fetch at render time** — rejected: a permanent external dependency + a phone-home/tracking
  vector on every preview open. Snapshot-once is the air-gap-compatible shape.
- **Caption/OCR images through the VLM into retrievable text** — rejected: runs the vision model on
  untrusted web pixels and puts model-synthesized text into the trusted store. Display-only keeps the
  attack surface to "render bytes," never "reason over bytes."
- **Per-host consent vetting** (the original plan's rec (c)) — rejected by the LA (c.1088): a hostname
  is not human-judgeable for danger; the framing trains rubber-stamping. Replaced by coarse per-article
  consent + the technical controls owning danger.
- **A second, image-specific egress door** — rejected: two doors is two SSRF/adjudication surfaces to
  keep in sync. One door, a binary mode, the frozen text contract untouched.

## Amendment 1 — Headless go-live blockers closed (2026-06-15, still DORMANT)

The HEADLESS subset of the go-live blockers (#663 c.1094) is implemented on
`feat/663-headless-blockers` — built + tested while the feature stays **FULLY DORMANT**. No image is
fetched or stored. A 5-dimension adversarial verification proved the locks hold at rest (including a live
repro that flipping ONLY `[knowledge].images_enabled` still denies because **no PA adjudicator is
registered** — the binary door shares the ONE PA adjudicator with the text door, there is no separate
"binary adjudicator") and surfaced 8 findings (3 code defects + 5 test-coverage gaps), all serviced
(2 deferred to test-harness ticket #665). The independent Guide review then added BED-1 (below). What
this Amendment changes in the record above:

- **#1 — gateway flag WIRED.** The gateway no longer ignores the config flag: it threads the AO-resolved
  `[knowledge].images_enabled` (read off the already-started orchestrator service — one source of truth,
  no second TOML parse) into the ingest coordinator's fetch gate. The flag still defaults false; going
  live is STILL a ceremony, not one toggle (it also needs the adjudicator + the egress allowlist + the
  #662 CD-ISO re-provision). The "gateway does not read the flag" residual is CLOSED.
- **#7 — sub-32px drop IMPLEMENTED.** `MIN_IMAGE_DIMENSION_PX` has a consumer: header-only
  `image_dimensions` / `dimension_below_min` (PNG/JPEG/GIF/WEBP, no decode, never raises). It drops
  decorative spacers / tracking pixels in the coordinator's (dormant) fetch branch. Sub-decision
  (dormant, LA's at go-live): an UNREADABLE header is NOT dropped — capability-preserving; strict
  drop-on-unreadable is the alternative. **(Amendment 2, 2026-06-15: the LA RATIFIED drop-on-unreadable
  (TD-4) — an unreadable header now DROPS, inverting this sub-decision; and the sub-32px drop is
  restated as storage/display hygiene, NOT a tracking-beacon defense — the GET already happened, so the
  consent gate in decision 4 is the real beacon defense. See Amendment 2.)**
- **#2 — edit-approve cascade survival.** `submit_pending` migrates surviving images (those whose
  `blarai-img://<id>` ref the operator kept in the edited body) across the dedup-replace CASCADE —
  decrypt under the prior doc's AAD, re-encrypt under the new doc's, atomic with the replace. The
  migrated state is RESET to `pending` (a re-submit opens a fresh decision cycle), so `approve()`
  governs it correctly. CLOSED.
- **#3 — approve/reject image lifecycle.** `approve()` promotes a doc's pending images to `approved`;
  `reject()` **DELETEs** them. **RETENTION POSTURE — LA decision 2026-06-15: DELETE-on-reject.**
  Rejecting an article PURGES its encrypted image bytes at rest (data-minimization under the
  privacy-absolute mandate); only the doc TEXT tombstone (retained) + the `INGEST_REJECT` audit record
  remain. The PURGE is a true zeroing of the freed pages, not a row unlink: the knowledge bank opens with
  `PRAGMA secure_delete=ON` (UC-010 go-live prereq, WS2), so the deleted ciphertext is overwritten in
  place rather than left recoverable in freed pages (the zeroing reaches the main .db file at checkpoint — WAL mode, folded on connection close — as ADR-033 states and the SE-1 residual probe enforces). This DELIBERATELY DIVERGES from the doc-content tombstone — images are untrusted web bytes the
  operator explicitly rejected, so they are not kept. A neat consequence: with images purged at reject,
  the migration path (#2) can never encounter a `rejected`-state image (there is nothing left to
  migrate), so a re-ingest re-fetches fresh images rather than resurrecting purged ones. CLOSED.
- **#6 — store-time MIME re-validation.** `store_image` re-runs the door's validator
  (`validate_image_content`) on the bytes — a different trust domain than the fetch-time gate (off-disk
  staging + a host-supplied label) — refusing a mislabeled image and storing the SNIFFED mime. CLOSED.
- **#4 — forged-id FORMAT gate.** The WinUI resolver enforces the `\A[0-9a-f]{32}\z` id shape
  (full-string anchored — `^…$` would accept a trailing newline in .NET). Headless PRECURSOR; true
  set-membership validation against the document's stored ids needs a per-document valid-id manifest
  plumbed to the renderer and remains a go-live successor. C# id-gate test coverage is tracked at #665
  (no C# test project exists yet — a platform decision).
- **#5 — binary-door SSRF/ESCALATE tests.** Regression locks prove the binary door refuses an
  internal-resolving named host (no widen, no fetch) and routes an ESCALATE verdict through the #639
  consent path. CLOSED.
- **BED-1 — image purpose-deny (LA decision 2026-06-15, Guide-surfaced).** The four locks are NOT all
  independent for the image path: `fetch_external_binary` shares the ONE PA adjudicator with the text
  door, and the live operator adjudicator self-populates its egress allowlist per URL — so text
  URL-ingest go-live (which registers that adjudicator) would release the "adjudicator-not-registered"
  and "empty-allowlist" locks for IMAGES too, leaving the image door on `images_enabled` alone. Fix
  (`url_adjudicator.IMAGE_INGEST_DENY_PURPOSES` + a guard in the single `make_url_adjudicator` wrapper
  every registered adjudicator flows through): the shared adjudicator DENIES the image-ingest purpose
  (`uc003-image-ingest`) up front — before the PA is even consulted — until a separate image go-live. So
  the image path keeps two image-SPECIFIC locks that SURVIVE text go-live: **purpose-deny +
  `images_enabled`**. Lifting the purpose is part of the image go-live ceremony, never silent. (The
  dormant merge was already safe via `images_enabled=false`; this makes the defense-in-depth claim true
  at text go-live too.)

Standing gate 3492 → 3575 / 0 failed; WinUI `dotnet build` 0/0. The image path stays welded — at rest by
all four locks, and after text URL-ingest go-live by the two image-specific locks (purpose-deny +
`images_enabled`). **Remaining go-live work (unchanged, NOT headless):** register the shared PA
adjudicator (the same one the text door uses) + lift the image purpose-deny + populate the egress
allowlist + flip `[knowledge].images_enabled` + the #662 CD-ISO guest re-provision (the first
irreversible outbound GET, LA-present, own egress review); the live-pixel WinUI render + visual confirm;
the #4 set-membership manifest; the #665 C# test harness. Caps = 20/article remains the LA sanity-check
before go-live.

## Amendment 2 — Pass A decode-time safety controls + consent seam (2026-06-15, still DORMANT)

Pass A builds the **headless / Python-side decode-time safety controls and the egress-consent seam**
that must exist *before* the first image can ever be fetched — built + tested while the feature stays
**FULLY DORMANT** (no image fetched, stored, or rendered; the four at-rest weld locks + the two
image-specific go-live-surviving locks are unchanged). It also records six LA decisions (2026-06-15) and
corrects two doc overclaims. Built on `feat/663-image-go-live-passA`; the WinUI consent *prompt* + the
decrypt→render seam + the #665 C# test project are Pass B (out of scope here).

- **W1 / BED-3 — decompression-bomb ceiling (NEW; was an unguarded gap).** A PA-allowed 2 MiB image can
  *decode* to billions of pixels and exhaust host memory at render time; the byte caps bound only the
  *compressed* size. New header-only constants + checks (`MAX_IMAGE_DIMENSION_PX=16384`,
  `MAX_IMAGE_PIXELS=40_000_000`, `dimension_above_max` / the single coordinator gate
  `image_dimensions_ok`) drop any image whose header declares a larger edge or a bigger pixel area than
  the ceiling — **no pixel decode** (decoding to measure would be the attack). The ceiling is mirrored at
  the at-rest store boundary (`knowledge_bank.store_image`) for defense-in-depth. Ceiling values are a
  Guide default the LA may tune in one place.
- **W2 / BED-4 — truncated-image drop (was built-but-unread).** The fetch door already computed
  `BinaryFetchResult.truncated` (an over-cap image is incomplete bytes) but the coordinator never read
  it; it now drops a truncated image to a placeholder rather than storing a half-image.
- **W3 / TD-4 — drop-on-unreadable-header (LA RATIFIED; INVERTS Amendment-1 #7's sub-decision).** An
  image whose dimension header cannot be read now DROPS (fail-closed) — we cannot prove it is under the
  bomb ceiling, so we refuse to keep it. The primitive `image_dimensions` still returns `None` and
  `dimension_below_min` still returns `False` on `None` (unchanged); the DROP is the coordinator gate
  `image_dimensions_ok` failing closed on `None`. The rejected alternative (keep-not-drop,
  capability-preserving) was Amendment-1 #7's posture; the LA chose the stricter drop, accepting that a
  validly-encoded-but-unmeasurable image is refused.
- **W4 / PRIV-2 — generic pinned User-Agent on BOTH doors.** The shared `_fetch_raw` transport now sends
  one generic modern-desktop-browser `User-Agent` (and no Cookie/Referer), so an outbound fetch blends
  into ordinary traffic instead of self-identifying as BlarAI. Deliberately a fixed literal refreshed by
  hand (a per-build/auto-bumped UA would itself be a fingerprint) — the trade-off chosen over a
  self-identifying or churning UA. Governs the text door too (intended; it is the shared core).
- **W5 / CD-1 — coarse per-article off-site consent seam IMPLEMENTED (coordinator-side).** Decision 4's
  consent is now built as a logic + fail-closed seam: a same-site/off-site host classifier
  (`shared.security.image_egress_consent.same_site` — **exact host match**, case-insensitive; NO eTLD+1
  / public-suffix-list — that grain upgrade is teed up for the LA and lives in one function) and a
  single-verifier registry mirroring `escalation_consent` (no verifier wired / deny / timeout / error →
  off-site images DROP, never fetched). The operator's coarse per-article yes/no carries only the
  DISTINCT off-site host list (descriptors, never URLs/payload). **Paste/file ingests fetch NO remote
  images at all** (LA-locked) — only a URL-ingested article does; offline content must never silently
  become a network egress. The WinUI prompt that drives the verifier is Pass B; until it registers one,
  every off-site fetch fails closed. A dormancy-invariant test proves the `images_enabled=false` weld
  short-circuits ahead of all consent/fetch logic — the seam creates no path around the weld.
- **W6 / PRIV-1 — sub-32px drop restated (doc honesty).** The sub-32px drop (Consequences + Amendment-1
  #7) was described as a *tracking-pixel* defense; it is NOT a beacon defense — the drop happens *after*
  the GET, so a 1×1 beacon is already fetched. It is **storage/display hygiene**. The actual beacon
  defense is the **consent gate (decision 4 / W5)**: an off-site host is never reached without the
  operator's per-article consent.
- **W8 — doc-honesty notes.** SL-2: the `image_hash` column + index are written but **not yet consumed**
  for dedup (the only active dedup is the `image_id` UNIQUE constraint) — noted in `store_image`. SL-3
  (the stored mime is the SNIFFED one, not the raw label) is accurate as written. FIG-1: a benign
  host/guest asymmetry — the WinUI `ExtractImageId` normalises (`.Trim()`) and strictly validates the
  `\A[0-9a-f]{32}\z` shape, while the host `rewrite_image_refs` passes any `blarai-img://` ref through
  without re-validating the id shape; the render-time gate is the authoritative validator (fail-closed),
  and set-membership (go-live) is the real forgery defense. TD-5 (a test-docstring overclaim named at
  #663 c.1106) could not be precisely located from the reference and is flagged for the LA rather than
  silently dropped.

Standing gate (pre-pass) 3575 → Pass A adds net-new tests (consent seam, ceiling/gate boundaries,
truncated/unreadable/oversize drops, CD-1 paste/file + off-site consent, the real-resolver W7 test, the
TD-2 launcher boot-wiring test). **The dormant posture is unchanged** — no image is fetched or stored by
any test against a real host; `images_enabled` still resolves False by default; the four at-rest locks +
the two image-specific go-live-surviving locks all hold. The go-live ceremony (flip `images_enabled`,
lift the purpose-deny, register the adjudicator, populate the allowlist, enable the guest parser, the
first live GET) is unchanged and explicitly NOT performed here.
