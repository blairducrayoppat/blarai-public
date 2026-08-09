---
title: "P2 privacy pre-screen — §D annex for the integrity/privacy reviewer"
piece: P2
status: for-review-panel (integrity/privacy reviewer)
prepared: 2026-07-19 (P2 author session); revised 2026-07-19/20 (F-7 corrected per privacy panel Y-3)
standard: AUTHOR_KIT §D (same bar as the public-mirror leak gate); P2-verdict risk 2; author brief §"four trust-spine specimens"
---

# P2 privacy pre-screen

Method: (1) establish the public-exposure ceiling by checking every quoted/cited source against the
live public mirror (`blairducrayoppat/blarai-public`, checked via GitHub API + raw fetch 2026-07-19);
(2) confirm each trust-spine specimen presents as CLOSED with its remedy; (3) flag, line by line,
every draft passage that describes egress/policy machinery for the integrity reviewer's judgment;
(4) list what was excluded under "when unsure, exclude and flag."

## 1. The exposure ceiling (result: draft ≤ mirror everywhere)

The mirror's `BUILD_JOURNAL.md` (pre-rotation monolith: 19,167 lines, 402 entries) contains ALL EIGHT
specimen entries VERBATIM, including all four trust-spine specimens, at these mirror line numbers:
replay window 3479 · kill-switch 6091 · knowledge bank 6905 · unreachable ALLOW 11836 · validator
swallow 12173 · gate kill 12749 · two-right-things 12781 · recovery 14220. Every verbatim quote in
the draft comes from one of these entries (or LESSONS.md, also public — HTTP 200). Every code path
the draft's fixes describe was spot-checked public: `shared/security/guarded_fetch.py` ·
`shared/security/egress_guard.py` · `shared/constants.py` · `launcher/tests/conftest.py` ·
`shared/fleet/swap_state.py` (all HTTP 200 on the mirror).

**Conclusion: no sentence in the draft exposes machinery beyond what the public mirror already
exposes in the same or greater detail.** The draft is strictly a curation of already-public text plus
interpretation. (Caveat for the reviewer: "already public on our own mirror" clears the §D sourcing
bar by construction, but §D's residuals clause still applies — hence the per-line flags in §3, since
publication to HN/home-base is a large amplification of that exposure.)

## 2. The four trust-spine specimens — closed-with-remedy check

| Specimen | Presents as closed? | Remedy printed | Fix on main | Residuals as printed |
|---|---|---|---|---|
| Replay window (S1) | YES — "The single-use guarantee had a 25-second hole" is past-tense; fix section prints the derived-TTL structure + shared constant + contrast lock | derived nonce TTL; single source of truth | `73746050` (2026-06-09) | none asserted; draft adds no open threads |
| SSRF-precheck kill-switch (S2) | YES — collision described in would-have grammar ("would have been denied and would have tripped"); fix = pre-arm resolver seam + armed-guard regression test | inspect-only pre-arm resolver seam | `c6fe7e97` (2026-06-12) | entry's own "Next" items (mTLS re-provision, kill-switch live exercise) are NOT in the draft — nothing reads as an open hole |
| Unreachable ALLOW (S4) | YES — before/after measured (31/35 → 35/35); deny-side probes doubled BEFORE loosening; committed baseline locks drift | two-line format + cap 24; probes-first discipline; eval baseline | `24a1ebd4` → `51182e4e` (2026-07-02) | trade-off (false-ALLOW surface opens) printed WITH its mitigations — deliberate, per the entry |
| Leak-validator swallow (S5) | YES — held answer is past-tense; fix = fifth provenance tier; regression pins pasted-external stays screened | UNTRUSTED_WEB tier, leak-feed-exempt only | `4373e95d` (2026-07-02) | none asserted |

None of the four is written as "collision" without "fix shipped." No specimen in the draft (including
the non-trust-spine four) describes an open vulnerability; specimen 8's bug is fixed upstream (PR
#4082 merged 2026-07-08, API-verified) and the draft's only open-ended sentence ("this catalog will be
wrong somewhere too") is epistemic, not a vuln reference.

## 3. Line flags for the integrity reviewer — every passage describing egress/policy machinery

The two egress-adjacent specimens (S2, S5) get the hardest screen per the brief; S1/S4 are
policy-machinery; a handful of framing lines also touch the machinery. For each flag: the draft
passage (by section + phrase), what it reveals, and the mirror-exposure status. Author's
recommendation on each: KEEP (public already + closed) unless marked otherwise.

**Opening + Specimen 2 (egress door / kill-switch):**
- F-1. Opening ¶2–3 + S2 setup: kill-switch "armed at process entry"; trips on "any network touch
  that is not on the allowlist"; re-air-gaps pending "a recovery ceremony". Reveals: arming point +
  deny-by-default posture + operational consequence. Mirror: verbatim-class content in entry (6091).
  KEEP.
- F-2. S2 setup: resolve-before-widen ordering; "a test asserts an internal-resolving host is refused
  with the allowlist never even briefly widened." Reveals: anti-SSRF design property. Mirror: yes.
  KEEP.
- F-3. S2 fix: "the door's inspect-and-refuse lookup goes through the guard's own pre-arm resolver — a
  path that can only inspect resolved addresses and refuse; it never connects." Reveals: existence of
  a deliberate resolver seam inside the guard. This is the single most sensitive sentence in the
  draft (it names a bypass-shaped seam, even though it is inspect-only and auditable). Mirror: yes,
  in MORE detail (the entry names the seam identifier `real_getaddrinfo`; the draft does not).
  KEEP with reviewer sign-off; fallback wording if the reviewer wants it narrower: "through a
  resolver path that exists before the guard arms, which can only inspect and refuse."
- F-4. EXCLUDED from draft (listed so the reviewer knows it was considered): the per-session
  go-live mechanics from the same entry — the environment-variable/CLI-flag re-weld design, the
  named override, the desktop-shortcut path, and the UAC/elevation environment-forwarding behavior.
  Public on the mirror, but they describe how the door is OPERATED, add no pedagogical value to the
  collision, and fail "when unsure, exclude." EXCLUDED.

**Specimen 5 (egress relay / output validator):**
- F-5. S5 setup/collision: the go-live chain ("deterministic allowlist released the approved search
  domain"; "HTTP 200"); the held-verdict line "leakage score 0.930 against a threshold of 0.85."
  Reveals: allowlist-release flow + live Stage-5 threshold value. Mirror: verbatim (12173), including
  the provider name — the draft is NARROWER than the mirror (provider not named; see verification-memo
  open item 4). KEEP.
- F-6. S5 fix: five-tier provenance structure; which tiers are leak-feed-exempt; pasted-external
  stays screened. Reveals: the validator's feed topology — an attacker-relevant fact (web-sourced
  content is not cosine-screened on output). Mitigation printed IN the same paragraph: action-lock,
  datamarking, per-dispatch deny all remain on those tiers. Mirror: yes, in more mechanical detail
  (filter predicates, enum names at the ingest site). KEEP with reviewer sign-off.

**Specimen 1 (token machinery):**
- F-7. S1: ES256 capability JWTs; 128-bit nonce; HISTORICAL TTL values (5 s nonce window / 30 s
  token validity, both pre-fix); replay-window mechanics; single live destination validator.
  Reveals: token design + the historical constants only — the draft does NOT print the current
  validity value (the fix's 30→5 change is recorded in the non-publishing claims table, not the
  draft; the draft's fix paragraph describes the derived-TTL structure without numbers).
  [Corrected 2026-07-19/20 per privacy panel Y-3: this flag previously overstated the draft's
  disclosure as "CURRENT 5-second validity."] Mirror: yes, incl. file/line references the draft
  omits. KEEP (printed values are historical; the design constants are public in both journal and
  `shared/constants.py`).

**Specimen 4 (policy classifier):**
- F-8. S4: decision-matrix condition (ALLOW ∧ confidence ≥ 0.75); zeroed fallback; escalation band
  existence; token cap 10→24; two-line output format; probe families (named at class level:
  credential reads, persistence writes, log destruction). Reveals: classifier plumbing + the
  categories the deny-side eval probes. Mirror: yes, including the probe IDs the draft omits. KEEP.
  Note for reviewer: draft deliberately does NOT reproduce probe text or exemplar wording (only class
  names), so it does not hand over a prompt-evasion cookbook beyond what the mirror already shows.

**Specimen 3 (knowledge-bank machinery, trust-adjacent):**
- F-9. S3: action-lock semantics for saved articles; 0.85 threshold; the 0.97 teeth-test; tier
  carve-out mechanics. Mirror: yes, in more detail. KEEP.

**Specimens 6–7 + coda (operational controls):**
- F-10. S6/S7: instance-lock refusal semantics (os._exit(1), no cleanup, release-never-called
  invariant); swap-recovery liveness protocol (pid + create-time stamp, fail-closed-to-recovery);
  fleet-root fallback behavior; LOCALAPPDATA-redirect scope gap (historical). Reveals: local-process
  operational controls — low external attack relevance (local machine, single operator); all public.
  KEEP.
- F-11. Coda: timeout values (90 s/600 s; ~15–18 s/180 s; 16 h) + the registry relation-lock control.
  Operational timing facts, public in journal + lessons. KEEP.

**Framing lines:**
- F-12. "The system, briefly": control inventory list (fail-closed, deny-by-default, one adjudication
  door, provenance tags, output validator, signed manifests, multiple independent locks on the one
  network door). Reveals: posture summary — identical to the public framing used in prior public
  posts and the mirror README-level docs. KEEP.
- F-13. "no cloud in the runtime path" (see claims-table G7): confirm wording does not overstate the
  air-gap (egress exists, policy-gated — specimen 5 makes this obvious in the same document). Reviewer
  to approve wording. KEEP pending that check.

## 4. Personal-data / framing / tone compliance

- Names: only the public handle appears (in the receipts URL); the human appears as "the operator" /
  "the owner" / "the project's operator." No other people named or implied. The upstream maintainers
  are NOT named in the draft (approvals are in the claims table only, which does not publish). OK.
- No local usernames, hostnames, absolute paths, or device identifiers beyond the published hardware
  spec (CPU/GPU/RAM — same as prior public posts). Draft grep-checked for `mrbla` / `C:\` / `C:/`:
  zero hits.
- Framing: "personal research project" ✓ · "long-term local AI system" ✓ · "prototype" absent ✓ ·
  "nearly done" absent ✓ · softened certainty in general claims (patterns section is explicitly
  hedged interpretation; n=1 limits section present) ✓ · exact numbers kept exact ✓.
- Tone: no vendor-bashing — specimen 8 is written in the collaborative-upstream register (bug
  characterized, sanitized reproducer, maintainers merged the fix promptly; the appreciation is
  stated plainly and briefly). No praise-seeking, no self-congratulation; failures stay in ("The
  killer was me" is quoted). Disclosure boilerplate present verbatim per §F. ✓
- Reconstructed dialogue: none. All quotes are from written records. ✓

## 5. Exclusions made under "when unsure, exclude and flag"

1. Go-live/re-weld operational mechanics (F-4 above) — excluded.
2. The specimen-2 entry's "Next" residuals (mTLS guest re-provision status, kill-switch live-exercise
   plans) — excluded; they read as open production-posture threads and are not needed for the
   collision. (They were subsequently closed in later entries, but the draft does not open the topic
   at all.)
3. Lesson numbers and ticket numbers in prose — excluded from the draft body (kept in the non-publishing
   annexes); they are public but add internal-bookkeeping surface with no reader value.
4. Probe texts / exemplar prompt wording from specimen 4 — excluded (class names only).
5. The internal seam identifier in specimen 2's fix (`real_getaddrinfo`) and file:line references
   throughout — excluded from the draft body; commit SHAs carry the checkability instead.
6. The search-provider name in specimen 5 — excluded pending reviewer call (public on mirror; open
   item 4 in the verification memo).
7. Any statement about the CURRENT armed/welded state of specific egress doors beyond "policy-gated,
   ceremony-opened" — the draft speaks about the June/July incidents historically and does not
   describe today's live door inventory.

## 6. Reviewer checklist (what I am asking the integrity reviewer to do)

1. Approve or tighten F-3 and F-6 (the two hardest flags — both egress-adjacent, both public already,
   both closed-with-remedy).
2. Rule on the provider-name question (F-5 / memo item 4).
3. Approve the G7/F-13 "no cloud in the runtime path" wording.
4. Confirm the §2 closed-with-remedy table reads as closed to a hostile reader, not just to us.
5. Sweep the draft for any residual I missed against the mirror ceiling — the claim to beat is §1's
   "draft ≤ mirror everywhere."
