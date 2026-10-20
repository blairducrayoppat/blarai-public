# Pre-push review: MXC proxy-egress Q3 and variant 4 evidence bundle (2026-10-16)

**Verdict: NO-PUSH.**

Under review: public evidence repository `windows-containment-evidence`, branch `feat/mxc-q3-standard-token-wfp` at
`f58650376ebdaf54b8466a87653a2a78563d0c02` (one commit on top of `main` `2e038a8`). Bundle
`evidence/2026-10-16-mxc-proxy-egress-standard-token-and-wfp/` (76 files): `runs/run-20261016-1` (standard token, BlarAI
#1799) and `runs/run-20261016-2` (WFP capture, #1798). Raw folders read read-only:
`%USERPROFILE%\blarai-research-data\mxc-proxy-egress\run-20261016-1` and `-2`. BlarAI main at `dbd61503`.
Reviewer: independent, non-elevated, did not write the bundle, changed nothing in it, pushed nothing.

## The LA's three conditions (#1768 c4266)

| | Condition | Finding |
|---|---|---|
| (a) | HOLD or plain refusal, never FAIL | **Confirmed.** Both batches HOLD 3 of 3 per arm (run records and `batch-summary.json` agree). Variant 4's FILTERS-PRESENT reading 6 of 6 and its failed positive control (`ok` false) are observations about the instrument and the filter set, not a containment failure. |
| (b) | LA saw the raw result first | **Confirmed for `run-20261016-1`; not fully for `run-20261016-2`.** #1799 c4348: he read Update 9 (Q3 and variant 4) about 12:45. Its push condition (2) names `run-20261016-1` only; nothing on #1798 or #1799 names a push of `run-20261016-2`. c4266 may cover it on its own terms, but that reading is a doubt. The ownership correction (#1798 c4352, appended to Update 9 at 17:20, after his read) changes an interpretation, not a raw figure; I reproduced it (below), so it is not a reason to withhold on its own. |
| (c) | Sanitiser re-count matches | **Confirmed.** `recount.py <raw> <sanitised>`: 70 / 70 figures, 0 differences (run-1); 99 / 99, 0 differences (run-2); both exit 0. Its sanitised-folder output is line-for-line identical to `RECOUNT.md`. My own independent count (separate script, own XML parse) matches every README figure. `.sanitized` totals match the PROVENANCE table exactly. |

The verdict is NO-PUSH because of findings 1 and 2: they are private data the sanitiser and the leak gate cannot see, new to
this repository, and not needed for any figure in the README.

## Findings, most severe first

1. **HIGH (privacy; costs: a public, permanent inventory of the operator's machine)** ·
   `runs/run-2026101{6-1,6-2}/run-*.json`, `snapshot_before/appcontainer_mappings` and `snapshot_after/appcontainer_mappings`
   (12 records, 218 entries each, 168 distinct package names) · The run records carry the full AppContainer mapping list of
   the machine: every installed Store package and sandboxed app, including vendor utilities that name the laptop maker,
   social, messaging and productivity apps, developer tools and the browser sandbox profiles. · Scenario: anyone reading the
   public repository gets the operator's software inventory and a stable device fingerprint, which the earlier pushed bundles
   never carried (`git grep` of `main` finds none of these names). The harness needs only the run's own profiles and the
   counts (`appcontainer_foreign_count`, `appcontainer_total`); the README cites no figure from the list. · Reproduced:
   `grep -rIl "microsoft.windowscalculator_8wekyb3d8bbwe" .` (any listed package serves) gives the 6 + 6 run records and
   nothing on `main`. The browser profile names are a hash of
   the browser's executable path: SHA-1 of the UTF-8 path reproduces three of the eight (Chrome, Edge, Firefox, all under
   Program Files). Hypothesis, not tested to the end: if any of the other five hashes a path under the user profile, a
   guessed account name could be confirmed offline. · Incidence: 12 of 12 run records; 0 in earlier bundles.

2. **MEDIUM-HIGH (privacy; the same class the bundle itself removed)** · `runs/run-20261016-2/wfp/*-filters.xml` (20 files)
   · Four stable IPv6 link-local interface addresses of the host (680 occurrences each across the dumps) are kept, while the
   sanitiser's bundle-local vocabulary replaced the host's LAN IPv4 address because it would identify a home network. The
   interface identifiers are stable per interface (not EUI-64, so no MAC is derivable), so they are a per-device identifier.
   · Reproduced: `grep -rIohiE "\b(fe80|fd[0-9a-f]{2}):[0-9a-f:]{2,}"` over the bundle lists four non-mask fe80 addresses;
   `git grep` of `main`'s `evidence/` finds none. · Incidence: 20 of 20 WFP dumps.

3. **LOW (sanitiser wrong spare, under the gate's sight line)** · `runs/run-20261016-2/wfp/*-during-filters.xml`, the
   `<asString>` line under each Tessera `providerData` (24 places) · The `sid-binary` rule zeroes the three domain values in
   `<data>` but leaves the `<asString>` rendering of the original bytes, where one printable byte of the third domain value
   survives. · Scenario: one byte of the 12-byte domain leaks, and the sanitised `<data>` and `<asString>` disagree; a blob
   with more printable bytes would leak more, and the gate cannot see it. · Reproduced: raw and sanitised lines compared side
   by side (the printable character is at the same offset in both). · Incidence: 24 of 24 blobs.

4. **LOW (process; the publishing control widened in the data commit)** · `tools/leak_gate.py`, `tools/sanitize.py`,
   `tools/allowed_guids.txt` in `f586503` · The branch is not "the bundle only": it adds a gate rule, two gate exemptions
   (`RESERVED_RANGE_BASES`, two allowed GUIDs) and a sanitiser rule in the same commit as the data that needs them. Every
   earlier gate or sanitiser change landed as its own commit with a review round. · Checked on the merits: the exemptions are
   exact addresses and exact constant keys (the two GUIDs are MXC's documented Tessera provider and sublayer keys,
   `docs/logging-access-denied.md:279-280` and `etl_decode.rs`); the new rule discriminates (a raw during-launch dump: 8
   `sid`, 4 `sid-binary`, 3,337 `guid` hits; the sanitised bundle: 0); `--self-test` 0 failures. No defect found in the
   change itself; the finding is that no independent review of the gate change is recorded.

5. **LOW (description narrower than the filter)** · README, table "The eight filters", Tessera row · The Tessera filters
   are described as keyed to the run's AppContainer SID; each also carries an `FWPM_CONDITION_ALE_USER_ID` security
   descriptor naming the account SID. · This matters to case 3's surrogate question, which is about connects made on the
   container's behalf by another identity. · Reproduced: own parse of all six during-launch dumps.

6. **LOW (an alternative left out of the attribution paragraph)** · README, "Which layer gave 10013" · B4 is called
   indistinguishable between two layers (capability, Tessera BLOCK); the WFP dumps the bundle ships also hold 728
   Bitdefender WFP filters (IGNIS, BDDCI4, VPN callouts), and the Conditions row says Bitdefender's rules "were not read". ·
   "Not measured" does list a possible Bitdefender contribution, so this is wording, not an omission of the limit: "at least
   two" and "present in the dumps, not analysed" would be exact.

7. **LOW (citation range)** · README, Ownership · `docs/logging-access-denied.md:260-264` is cited for "names these two
   keys"; the keys are at `:279-280`. `:248` ("MXC does not coordinate with WFP directly") and `base_container_helpers.rs:24`,
   `:94-97`, `:176`, `base_container_runner.rs:3231,3441`, `networking.md:121-124` all check out at `525d0f25`.

8. **INFO** · The root `README.md` index lists bundles up to 2026-10-14; neither 2026-10-15 bundle nor this one is listed.
   The precedent commits did not add rows either, so this branch follows precedent.

## Checked and not broken

- Identity: `scripts/scrub_public_identifiers.py --dir <bundle> --check`: 0 rewritten, 0 findings. `leak_gate.py --tree
  <bundle>`: 76 files, 0 hits; `--tracked`: 295 files, 0 hits; `--self-test`: 0 failures. Own greps: account name, host
  name, `S-1-5-21-<digit>`, `S-1-12-1-<digit>`, `Users\`, e-mail, private folder names, tracker numbers, the gateway's real
  address: 0. Private IPv4 left: only range constants and the WSL/Hyper-V switch range; the LAN /24 is replaced.
- Every README figure against the raw: dry-run, launch, B2 (container, proxy log, listener log: 3 per run), B3 and listener
  direct hits (0), B4(i), B4(ii), unconfined 12 of 12 per arm, state change 0, verdicts, wall times, refusal times (0.002 to
  0.027 s and 0.002 to 0.025 s), container token fields, PSEC 1.1 / 432 bytes in all 12 launcher logs, Bitdefender 16 at
  start and end, batch start and end times, filter counts 1008 / 1016 / 1008 with before == after key sets in all six runs,
  the eight new filters (names, layers, actions, weights 8 and 1, provider and sublayer keys, 6 keyed to the run SID and 2
  mentioning it), `capture_during_container_alive` 6 of 6, both control dumps byte-identical to the first before-dump,
  `wfp-control.json` fields. Same figures in BlarAI's `PERFORMANCE_LOG.md` entries and both
  `docs/performance/mxc_proxy_egress_*_2026-10-16.json`.
- Ownership, with the corrected wording (#1798 c4352): the `MXC-Loopback` SID derivation reproduces all seven
  sub-authorities, and the same computation reproduces a Store package's SID from the run records; `MXC-Loopback` is present
  once each in `wxc-exec.exe` and `mxc_ffi.dll`; "Tessera Sandbox" is in System32 `processmodel.dll` and in none of the 11 +
  65 exe and dll files of the two MXC build folders. The README states the peering is installed by the Windows Firewall
  service and that MXC's request for it is MXC's statement, not observed. That is the corrected wording.
- Over-claiming: which layer produced 10013 is stated as not answered; B3 is "by inference"; B4 is indistinguishable; scope is
  two builds, 26200.9711, TCP only, this policy, one machine; "not a claim that MXC is secure". Every NOT MEASURED item of
  the merged records is in the README's list.
- Probe copies: committed blobs of `proxy.py`, `net_payload.py` and `summarise.py` hash to the batch headers' values
  (`.gitattributes` `* -text`); `run_probe.py` and `launch.ps1` differ after the sanitiser's tracker and home replacements,
  which the README covers with "(before sanitising)".
- Precedent: PROVENANCE section with replacement counts and re-count, `.sanitized` per folder, probe-index row. The probe
  copies sit inside the bundle, not under `tools/probes/`; that is a reasoned difference (the 2026-10-15 harness already
  occupies that folder) and is indexed.

## What would clear a push

Findings 1 and 2 removed from the bundle (the mapping lists reduced to what the harness compares, the link-local
addresses replaced as the LAN address was), the bundle re-sanitised and re-counted, then a fresh pre-push review at the new
hash. Finding 3 is a sanitiser rule for `<asString>` beside a rewritten `<data>`. The `run-20261016-2` push scope (condition
b) needs either the LA's word or a recorded reading that c4266 covers it.

## Round 2: lock changes and the omitted state dumps (still at `f586503`)

During round 2 the evidence clone's working tree moved to the builder's rework branch `feat/mxc-q3-standard-token-wfp-r2`
(at `2e038a8`, with tool changes not committed). Everything below was read from commit `f586503` through `git show` and
`git grep`, never from the working tree.

Each change to a lock, judged as a possible weakening:

| Change | Direction | Judgement |
|---|---|---|
| `allowed_guids.txt` +`2f8c6d14-3b7e-4a59-9c08-1d4e7a6b2f30` (provider) | exemption | **Justified, exactly scoped.** A fixed Windows constant: its binary (little-endian GUID) form is compiled into System32 `processmodel.dll`. It appears in every one of the 20 kept dumps (registered provider, before, during and after) and in raw WFP dumps from 2026-10-11 of an unrelated study. MXC `525d0f25` names it (`docs/logging-access-denied.md:279`, `etl_decode.rs` tests). |
| `allowed_guids.txt` +`7b1e9a2c-9d4f-4c8a-b321-5e6d2f8a1c44` (sublayer) | exemption | **Justified, exactly scoped.** Binary form compiled into `processmodel.dll`; MXC `docs/logging-access-denied.md:280`; present only in the during-launch dumps (4 each), as the per-launch filters' sublayer. Not a per-machine value. |
| `leak_gate.py` `RESERVED_RANGE_BASES` (7 addresses exempt from `public-ip`) | exemption | **Scope exact, justification wrong (finding 9).** Seven exact IANA special-purpose base addresses, none anyone's address, so the scope is correct. But the code comment and PROVENANCE say they come from "the Windows firewall's built-in reserved-range filters". In the raw dump they are carried only by three filters named "Allow IPv4 LAN Traffic" under provider `{ba571967-8803-5000-ba62-1e789d97cac1}`, whose provider entry is named `Bitdefender.<number>-Provider`: a Bitdefender filter set, not Windows'. |
| `leak_gate.py` `sid-binary` rule, its all-zero placeholder exception | new refusal plus one narrow allowance | **Strengthens.** Refuses a domain SID written as hex; the allowance needs all three domain values to be `00000000` (the negative lookahead covers 24 zeros, so a partly real domain is still refused). Discriminates: a raw during-launch dump gets 4 `sid-binary` hits, the sanitised bundle 0. The remaining gap is finding 3 (`<asString>`). |
| `sanitize.py` `sid-binary` rewrite | new rewrite | **Strengthens.** Keeps the 12-byte header and the RID. Gap: finding 3. |
| `PROVENANCE.md`, `tools/probes/README.md` | prose and index | No lock. PROVENANCE repeats the wrong Windows attribution (finding 9). |

9. **LOW-MEDIUM (a lock widened on a false premise)** · `tools/leak_gate.py` (the `RESERVED_RANGE_BASES` comment) and the
   `PROVENANCE.md` "Changes to the tools" paragraph · The exemption is justified in writing as Windows built-in filters; the
   filters are Bitdefender's. · Scenario: a later reader trusts the comment, assumes the addresses can only come from Windows,
   and widens the set on the same reasoning; or reads the bundle as saying something about Windows' default filters. The
   exemption itself lets no person's address through. · Reproduced: own parse of the raw `A-A1-r1-075819-before-filters.xml`,
   filters carrying any of the seven bases, with their `providerKey`, and the provider list entry for that key.

10. **LOW (fingerprint)** · the 20 kept WFP dumps · The Bitdefender provider name embeds a .NET tick count. Converted, it
    is 2026-10-15 23:33:47, which is the machine's Bitdefender reinstall that evening. One device-specific event time, 20
    occurrences, not on `main`.

**The omitted state dumps.** The README ("Not included from the raw folders, and why") and PROVENANCE both state the
omission of the 20 `wfp/*-state.xml` dumps (about 61 MB, the machine's recent network events) and name the two facts that
rest on them alone. At `f586503` the bundle holds 0 files named `*state*` and 0 files containing `netEvent`; the raw folder
holds the 20. **No remote address leaked:** an `ipaddress` scan of every bundle file finds, as IPv4 outside the private,
loopback, link-local and multicast ranges, only netmasks, `1.1.1.1` (the measurement target) and the seven IANA bases; as
global IPv6, only well-known prefixes (`64:ff9b::`, `2001:20::`, `::ffff:0:0:0`) and multicast. The IPv6 link-local
addresses are finding 2.

**Builder's "decisions and deviations" items 1-4:** requested from `q3-evidence-builder`; no reply before this commit. They are
judged in the report to the team lead when the reply arrives.

## Round 3: the rework, tools `7f3f9c4` and data `848f50c` (branch `feat/mxc-q3-standard-token-wfp-r2`)

**Verdict at `848f50c`: NO-PUSH.** Findings 9 and 10 are not fixed, and the LA's decision on #1798 c4368 makes closing
findings 1, 2, 3, 9 and 10 a condition of the push. Read from `git archive` extractions of each commit, never from the
shared working tree.

Condition (b) for `run-20261016-2` is settled: #1798 c4368 records the LA's "Yes" (2026-10-17 about 00:00) to push the
sanitised variant-4 batch with Q3, after a clean pre-push review of the fixed bundle.

| Finding | Status at `848f50c` | Evidence |
|---|---|---|
| 1 package inventory | **FIXED** | All 24 `appcontainer_mappings` arrays read `[]`; `appcontainer_total` 218 and `appcontainer_foreign_count` kept; 0 files hold any package name; `.sanitized` `inventory` 2,616 per batch (218 x 12 arrays). README states the removal. |
| 2 IPv6 interface addresses | **FIXED** | The only `fe80::` forms left are the prefix (401) and the mask (340); the four addresses read `ipv6-interface-1` to `-4` (680 each in the dumps). README states the replacement. |
| 3 `<asString>` residue | **FIXED** | All 24 SID blobs now render as all dots; the new `sid-binary-asstring` gate rule refuses a stale rendering (self-test case passes). |
| 4 gate change without its own review | **Addressed by form** | Tools now a separate commit with a self-test case per rule; this round is its review (below). |
| 5 Tessera user-ID condition | **FIXED** | README row now names the `ALE_USER_ID` condition and leaves the surrogate case as not tested. |
| 6 "two candidates" | **FIXED** | "at least two candidates" and the 728 Bitdefender filters named as present and not analysed. |
| 7 citation | **FIXED** | `:279-280` names the keys. |
| 9 reserved-range justification | **NOT FIXED** | `tools/leak_gate.py:159` and `PROVENANCE.md:229` still say the seven addresses come from "the Windows firewall's built-in reserved-range filters"; in the dumps they are carried only by the Bitdefender provider's "Allow IPv4 LAN Traffic" filters. |
| 10 Bitdefender provider timestamp | **NOT FIXED** | `Bitdefender.<ticks>-Provider` is still in all 20 kept dumps (the tick count decodes to the evening's reinstall time). |

Tools commit `7f3f9c4`, judged as locks:
- New refusals (`appcontainer-inventory`, `ipv6-interface`, `sid-binary-asstring`) only tighten. `--self-test` at `7f3f9c4`:
  100 PASS, 0 failures. The whole tree at `7f3f9c4` (219 files) and at `848f50c` (295 files): 0 hits, so no existing bundle
  trips the new rules.
- Probed inputs: a bracketed upper-case global IPv6 with a port and a scoped link-local with an interface name are refused;
  clock times, masks, prefixes, `::1`, `ff02::` and documentation addresses pass (self-test). The raw dumps write IPv6 only
  in colon form (checked: no hex byte-array form), so the rule sees every address there.
- **LOW, wrong spare, hypothesis-grade incidence 0:** `appcontainer-inventory` matches only "package SID, white space, name".
  The same pair written `SID: name`, as a JSON key and value, or name-first passes the gate (reproduced with three crafted
  files). The probe writes only the first form and the bundle holds no other, so this does not block. It is a rule narrower
  than the question it answers.
- Exemptions unchanged from round 2: the two Tessera GUIDs are justified; `RESERVED_RANGE_BASES` is exact but mis-justified
  (finding 9).

Data commit `848f50c`: scrub `--dir --check` 0 / 0; gate `--tree` 0 hits; `recount.py` raw against sanitised 70 / 70 and
99 / 99, 0 differences; my own count unchanged and matching the README; all 20 XML dumps and all JSON records parse. **LOW,
wording:** PROVENANCE says "218 in each of the 12 `appcontainer_mappings` arrays of the 12 records" in a per-folder row; each
folder has 6 records and 12 arrays.

**Do the self-tests bite?** I disabled each new refusal in an extracted copy of `7f3f9c4`, one at a time (replaced its
`add(...)` call), and ran `--self-test`: `sid-binary` off gives 2 failures, `sid-binary-asstring` off 1, `appcontainer-inventory`
off 1, `ipv6-interface` off 1; restored, 0. Each new detection has a self-test that fails when the rule is off.

**Conditions at `848f50c`:** (a) re-confirmed: HOLD 3 of 3 per arm in both batches, from the sanitised records. (b) settled for
both batches (#1798 c4368). (c) re-confirmed: the re-count is 0 differences for both batches, and `.sanitized` totals match the
new PROVENANCE table.

**The builder's "decisions and deviations" 1-4** (received after the commit above, written about `f586503`):
1. State dumps left out rather than hand-edited, with the two facts that rest on them named: **accepted**. Verified (round 2):
   0 state files and 0 net events in the bundle, and no remote address.
2. `sid-binary` added after finding the hex SID that both tools missed: **accepted**. Its `<asString>` gap (finding 3) is
   closed in `7f3f9c4`.
3. Tool edits: the two Tessera GUIDs are **accepted** (Windows constants, round 2); the gateway and LAN replacements are
   **accepted** (no 10.0.10.x left; same method as the case-1 precedent); the reserved-range description is **rejected as
   written**. The builder concedes it is wrong (finding 9).
4. Commit trailer without an e-mail address, because the repository's `commit-msg` gate refuses one; hook not bypassed:
   **accepted**. The public repository's own gate governs its commits.

**Moving tree:** after `848f50c` the builder added `5e0d2d9` ("correct the reserved-range comment ...; device-timestamp rule
for the Bitdefender provider tick count"), a tools commit with no re-sanitised data on top of it. It is **not reviewed here**.
Findings 9 and 10 are open at `848f50c`. Closing them needs `5e0d2d9` plus a data commit re-sanitised with it, then a review
at that hash.

## Round 4: tools `5e0d2d9`, data `b653882` (branch `feat/mxc-q3-standard-token-wfp-r2`)

**Verdict at `b653882`: PUSH-OK.** Branch `2e038a8..b653882` = 4 commits: tools `7f3f9c4`, data `848f50c`, tools `5e0d2d9`,
data `b653882`. Read from a `git archive` extraction of `b653882`.

**Tools `5e0d2d9`, on its own:**
- Finding 9 **FIXED**. The `RESERVED_RANGE_BASES` comment now says that the seven addresses appear in three "Allow IPv4 LAN
  Traffic" filters of a Bitdefender provider and in no Windows filter, and names each address's registry (RFC 6598, 6890,
  5737, 7526, 2544). The new self-test checks that exactly seven bases pass and that the next address after four of the bases
  is still refused. The exemption is exact and its justification now matches the dumps (round 2 parse).
- New `device-timestamp` refusal (`Bitdefender.<15-19 digits>-Provider`) and sanitiser rule `ticks` (writes `TICKS`): this
  only tightens.
- Toggle check at `b653882`'s tools: each rule switched off in turn gives these self-test failures: `device-timestamp` 1,
  `sid-binary` 2, `sid-binary-asstring` 1, `appcontainer-inventory` 1, `ipv6-interface` 1. With the reserved-range exemption
  removed, the self-test fails 1 (the exemption is tested in both directions). With all rules restored, 0 failures.

**Bundle `b653882`:**
- Finding 10 **FIXED**: the provider name reads `Bitdefender.TICKS-Provider` in all 20 dumps; no tick count remains; no
  other name in the dumps carries a run of 12 or more digits.
- Findings 1, 2 and 3 still closed: 0 package names; only the `fe80::` prefix and mask remain; all 24 SID blobs render as
  dots. PROVENANCE now gives the Bitdefender source for the reserved-range addresses and has a `ticks` column (20).
- Identity and leak checks: scrub `--dir --check` 0 rewritten, 0 findings; gate `--tree` on the bundle 76 files, 0 hits; on
  the tracked tree, 0 hits (the only hits in a whole-extraction scan were the `__pycache__` files my own self-test runs
  created, not tracked files); `--self-test` 0 failures; the four commit messages pass `--message`; author and committer are
  the code host's no-reply address, as in the precedent commits. Own greps: account name, host name, `S-1-5-21-<digit>`,
  `Users\`, the gateway's real address, e-mail, private folder names: 0 files.
- **(a) re-confirmed:** HOLD 3 of 3 per arm in both batches (sanitised records; all per-arm counts as in round 1).
- **(c) re-confirmed:** `recount.py` raw against sanitised 70 / 70 and 99 / 99, 0 differences; my own count unchanged, matching
  every README figure; filter counts 1008 / 1016 / 1008, before == after, 8 new per launch in all six; `.sanitized` totals
  match the PROVENANCE table.
- **(b)** settled for both batches: #1799 c4348 (`run-20261016-1`, after the SID scrub merged, which it has: `899bc51c` on
  BlarAI main) and #1798 c4368 (`run-20261016-2`).

**Residuals, not blocking:**
- `appcontainer-inventory` sees only the "package SID, white space, name" form. `SID: name`, a JSON key and value, and
  name-first pass the gate (reproduced in round 3). Incidence 0: the probe writes only the first form, and the sanitiser
  empties the only arrays that hold it.
- `device-timestamp` covers only Bitdefender's provider-name form. Another product's tick-stamped name would pass. Incidence 0
  in these dumps (no other 12-digit-plus run in any name).
- PROVENANCE wording, LOW: "218 in each of the 12 `appcontainer_mappings` arrays of the 12 records" (per folder: 6 records, 12
  arrays).

## Round 5: tools `8c48911`, data `425795e` (branch tip, frozen)

**Verdict at `425795e` (`425795e2b8f9e00a4560576fd0abcb1e81957620`): PUSH-OK.** It supersedes the round-4 verdict at
`b653882`. Read from a `git archive` extraction of `425795e`.

**Tools `8c48911`, on its own (only `tools/leak_gate.py` changes):**
- **It only tightens.** The refusal pattern is now the old `INVENTORY_ENTRY_RE` OR two new alternatives (SID then joiner then
  package-looking name; package-looking name then joiner then SID), so it refuses a strict superset of what it refused before.
  The new "field name" case is a self-test that `appcontainer_sid` and `container_sid` beside a SID, and the probe's own
  `mxcfx-` profiles, do not hit. It adds no allowlist or exemption in code: those inputs never matched the old pattern either.
- **Its toggles bite.** With the rule's `add(...)` switched off, 7 self-test cases fail. With the refusal reverted to the old
  pattern only, 5 fail (the new joiner and order forms). Restored, 0 failures.
- **Residual 1 is narrowed, not closed.** Still passing the gate, reproduced: a package name with neither a dot nor a
  13-character publisher id in a non-space form (`"SID": "windows_ie_ac_001"`), a `|` or `;` joiner, and SID and name in
  separate XML elements. Incidence 0: every `appcontainer_mappings` array in the bundle is empty, and the tracked tree has 0
  hits. Not blocking.

**Data `425795e`:**
- Changes no data. `git diff b653882 425795e` touches only `PROVENANCE.md` (one line) and `tools/leak_gate.py`; `evidence/` is
  identical to `b653882`. The PROVENANCE line now reads "218 in each of 12 `appcontainer_mappings` arrays: 6 records per
  folder, two snapshots each", which closes residual 3.
- Gate `--tree` on the bundle: 76 files, 0 hits; on the full extraction (295 tracked files): 0 hits; `--self-test` 0
  failures. Scrub `--dir --check`: 0 rewritten, 0 findings. `recount.py` raw against sanitised: 70 / 70 and 99 / 99, 0
  differences.
- (a), (b), (c) as in round 4. The bundle is byte-identical to `b653882`, where all three were confirmed, and the gate,
  scrub and re-count above were re-run at `425795e`.

**Residuals at `425795e`, none blocking:** the inventory shape gaps above, and `device-timestamp` covers only Bitdefender's
provider-name form. Both have incidence 0.

## Suites run

At evidence `f586503`: the scrub `--dir --check`, `leak_gate.py --tree`, `--tracked`, `--self-test`; the bundle's
`recount.py` raw against sanitised for both batches; my own count and filter parser over raw and sanitised; a leak-gate
discriminating split on one raw WFP dump. At BlarAI `dbd61503`: read-only reads of the records. No pytest run.
