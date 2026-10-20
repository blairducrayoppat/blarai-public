# Adversarial review, round 1: the case-4 probe (`ncoprobe.exe`)

Date: 2026-10-19 (local clock read at the start: 17:39 -04:00). Reviewer: independent adversarial reviewer (did not write the code; reports, never repairs).

## Verdict: FAIL for live use

Two findings block a live run: **P1-1** (the operator's personal e-mail address lands in every S and A record and survives the public scrub with
`--check` green) and **P1-2** (status `0x80320028` is `FWP_E_OUT_OF_BOUNDS`, not an access-denied code, yet the probe classes it `denied` and its
own self-test mandates that). P1-3 and P1-4 are cheap, one-place changes whose cost when they fire is a false verdict or a STOP in the middle of the
Lead Architect's ceremony; I recommend they land in the same fix round. P1-5 to P1-8 do not block.

The engine-safety design held under every attack I could make without opening the engine: no refusal vector reached the engine entry, and the shipped
build cannot be toggled by environment.

## What was reviewed, at which hash

`<nco>` below is `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco`.

| File | sha256 (raw bytes; LF-normalised is identical for `NcoProbe.cs`) |
|---|---|
| `<nco>/probe/NcoProbe.cs` | `52afc31fbffb61e0080cb0499e78f74b8dd537ea26022a533dafba2c5eea0848` |
| `<nco>/probe/build-probe.ps1` | `182d7ca17258adf27c5636d3ebaa969053ea17492361e7fb62d8c3eae9cbf944` |
| `<nco>/probe/run-probe-selftest.ps1` | `d1c10b4201b6017f0f9049dfd4d19e5cdbee40064f3068183ae4b73ad1779b3b` |
| `<nco>/probe/README.md` | `58d7adf6fdfaace5ee1bc26d7b4ccb48ae98077ccc065fecbf9215d1f53d432f` |

These four files were committed in `fa96f8e7` and are unchanged at the worktree head `f12f1b00` (that commit touched only the driver and its README).
The tree moved during the review; every probe result below was produced from the bytes above. Driver line numbers cited below are at `f12f1b00`.

## Findings

### P1-1 BLOCKING: the operator's Microsoft-account e-mail is written into every S and A record, and the public scrub does not remove it

- **Where:** `NcoProbe.cs:1094-1098` (`AddLookup`, called for every group at `:1177`) writes the `LookupAccountSid` name of every group SID.
- **What is wrong:** on the operator's token the cloud-account group `S-1-11-96-...` resolves to `MicrosoftAccount\<his e-mail address>`, so `identity`
  and every S and A record carry his personal e-mail. The repository scrub rewrites that SID (rule 5), the host name and the account name, but not
  the resolved name; after the rewrite `--check` passes. A sanitised `runs/` copy (SPEC Part 3) would carry the e-mail into the repository and the
  public mirror with every lock green.
- **Cost when it fires:** an irreversible privacy leak, silent in every gate.
- **Reproduced.** `identity` from the shipped exe through `run-limited.ps1` (Medium integrity), then the scrub on a scratch copy of that output:

```
I1 identity shipped   exit 0
    groups 16; cloud-account groups 1; their names carry '@': 1; their name prefix: MicrosoftAccount
python scripts/scrub_public_identifiers.py --dir <scratch>\scrubtest --check      -> FAIL ... identifier present; exit 1
python scripts/scrub_public_identifiers.py --dir <scratch>\scrubtest --log <scratch>\out\scrub-dir-log.md   -> 1 file(s) rewritten; exit 0
after the scrub: cloud-account group sid(s) = S-1-11-__ACCOUNT__; their name carries '@' = 1; '@' anywhere in the file = True;
                 host name present = False; account name present = False
python scripts/scrub_public_identifiers.py --dir <scratch>\scrubtest --check      -> 0 finding(s); exit 0
```

- **Incidence:** no banked record in `docs/research` or `docs/performance` carries a `MicrosoftAccount` name today (grep: none). This probe would be
  the first instrument to write one. `scripts/identity_lock.py` has no rule for e-mail addresses or cloud-account names.
- **Note:** the SPEC asks for "the resolved name when LookupAccountSid can give one", so the probe is SPEC-conformant. The gap is that neither the
  SPEC's sanitisation plan nor the scrub covers this datum. Least data at the source is the only control that does not depend on a later step.

### P1-2 HIGH (blocking): `0x80320028` is `FWP_E_OUT_OF_BOUNDS`; the probe classes it `denied`, and the self-test mandates the misclass

- **Where:** `NcoProbe.cs:174` names the constant `FWP_E_ACCESS_DENIED = 0x80320028`; `:1499` puts it in the denied set; `:2168-2177`
  (`rc.classify_add`, `rc.classify_delete`) require `denied` for it. The premise is SPEC.md:111 and probe README.md:217 (amendment 6, "as the halfset
  harness does"), inherited from `harness/halfset.rs:86`. The driver mirrors it at `spike-nep5-nco.ps1:201` and `:1794`, and `scripts/README.md:194`.
- **What is wrong:** no `FWP_E_ACCESS_DENIED` exists. The installed SDK defines `0x80320028` as `FWP_E_OUT_OF_BOUNDS`, "An integer value is outside the
  allowed range" (`Windows Kits\10\Include\10.0.26100.0\shared\winerror.h:51786`).
- **Concrete failure:** an add rejected because a value is out of range is recorded, tabulated by `-Collect`, and would be cited in C27 as the principal
  being denied. That is the headline verdict of the experiment. The raw status is kept beside the class, but the class is what the table and the claim
  use. A lock that asserts the misclass is a lock that mandates a defect.
- **Reproduced:**

```
certutil -error 0x80320028
  0x80320028 (-2144206808 FWP_E_OUT_OF_BOUNDS) -- 2150760488 (-2144206808)
  Error message text: An integer value is outside the allowed range.
reviewer harness (probe source compiled with a test entry point): U06 ClassifyAdd(0x80320028) => denied ; ClassifyDelete(0x80320028) => denied
```

- **Incidence:** zero records with that status in the banked tree. Whether `FwpmFilterAdd0` can return it for this filter was not testable.
- **For the case-4 lead, outside this review's four files:** the matrix harness `halfset.rs` carries the same mislabel. Its banked results should be
  checked for that status before any of them is cited as a denial. I found none in `docs/`.

### P1-3 MEDIUM: a WFP call that throws is recorded as status `0x00000000`, class `succeeded`

- **Where:** `NcoProbe.cs:1466-1472` and `:1477-1483`. `AddAttempted`/`DeleteAttempted` are set before the call, `AddRc`/`DeleteRc` default to 0, and the
  catch records only `error`. `Outcome.AddTo` (`:1547-1558`) then renders the default 0.
- **Concrete failure:** if the add P/Invoke throws (for example an `SEHException`), the record says the add succeeded. It also says `filter_id 0`,
  `overall ok` and exit 0. The driver's `Test-C4Record` finds the status and class consistent and counts the record. An F record would then claim the
  delegated account can add a filter. This is an absence rendered as a confident value.
- **Reproduced at the rendering level.** The trigger, a throwing call, is a hypothesis: an access violation would crash the process rather than be caught.

```
U05 outcome when both calls threw => "add": { "attempted": true, "rc": "0x00000000", "class": "succeeded", "filter_id": 0, "present_after": "unreadable",
    "get_rc": "0x00000000", "error": "System.Runtime.InteropServices.SEHException: simulated" }, "delete": { "attempted": true, "rc": "0x00000000",
    "class": "succeeded", ... }, "overall": "ok", "residue": "unknown", "exit": 0
```

- **Incidence:** 0 (no engine run has happened).

### P1-4 MEDIUM: no check before the engine that the principal matches the condition

- **Where:** `NcoProbe.cs:1745-1764`. After `Identity.AddFacts`, the only refusal is `userSid == null`. `is_expected_account` is computed (`:1232`) and
  recorded, but never consulted.
- **Concrete failure:** an E run elevated as the operator reaches the engine. Two routes lead there: the one-step elevation the run sheet warns
  against, or a UAC credential prompt answered with his own account (`RUN_SHEET.md:59-61` relies on him noticing). His elevated token then adds and
  deletes the persistent filter. `-Collect` sees an F/E record whose add succeeded under the wrong principal and STOPs with exit 9
  (`Test-C4WrongAccountAdd`, SPEC Part 2 stop conditions). The stopping mode cleans nothing up, and the session falls to the manual path.
- **Design gap; not reproduced** (it needs the engine). The code path was read.
- **SPEC status:** conformant. The SPEC built a STOP for exactly this slip. A refusal before `FwpmEngineOpen0` would make the slip cost nothing and
  would remove an engine write by the wrong principal. Under that refusal, F/E would require `is_expected_account` true and S/A would require it false.
  Adding it is the case-4 lead's decision (a SPEC amendment).

### P1-5 MEDIUM: the constant locks compare the file with itself; a both-sided constant edit passes every check

- **Where:** `NcoProbe.cs:2043-2084` (`constants.guid_text`, `constants.values`) compare each `K` constant with a literal in the same file.
  `selftest-process` (`:2710-2718`) compares `--version` with `K` of the same build. The proof binds only sublayer, provider, filter key and user SID.
- **Concrete failure:** the layer, condition GUID, action, weight, flags, match type and condition-value type are pinned by nothing outside the file.
  The SPEC asks for "the fixed constants equal to the ones in this table"; the lock certifies only that the file agrees with itself.
- **Reproduced (mutant MB4):** both occurrences of the IPv4 connect layer GUID were replaced with the IPv6 connect layer GUID in a copy of the source,
  built with the author's `build-probe.ps1`, and run as the runner does:

```
MB4 --version layer constant: 4a72393b-319f-44bc-84c3-ba54dcb3b6b4
MB4 selftest exit 0: checks_run 66, checks_failed 0
MB4 selftest-process exit 0: checks_run 92, checks_failed 0
```

- **Current values are correct.** I checked every one against the installed SDK headers: `fwpmu.h:457-461` (ALE_AUTH_CONNECT_V4), `:1887-1891`
  (ALE_USER_ID), `fwptypes.h:230` (FWP_ACTRL_MATCH_FILTER 0x1), `:303-308` (BLOCK = 0x1001), the FWP_DATA_TYPE enum (UINT64 4, SECURITY_DESCRIPTOR_TYPE
  14), and `fwpmtypes.h:471` (FILTER_FLAG_PERSISTENT 0x1). They also match the matrix library. So this is a lock that over-certifies, not a wrong
  constant today.
- **Incidence:** n/a.

### P1-6 LOW: the source scans miss ordinary evasions, and the README credits them with more than they test

The plain forms are caught: all three controls fail as they should. Five ordinary variants pass. The probe's own `ProcessTest.SourceScans` was run by
reflection over mutated copies of the source text; nothing mutated was executed.

```
MS1 control: plain GetEnvironmentVariable("NCOPROBE_X") outside the toggle branch  -> toggle_code_only_in_the_toggle_branch=FAIL
MS2 Environment.ExpandEnvironmentVariables("%NCOPROBE_X%") in Proof.Validate         -> all scans pass
MS3 "#if NCOPROBE_TOGGLE / #elif true / env read / #endif" in Proof.Validate          -> all scans pass
     (compiled without the toggle define: the shipped-flavour binary carries NCOPROBE_X = True; the genuine shipped exe: False)
MS4 a second "Native.FwpmFilterAdd0 (h, ...)" call, space before the parenthesis      -> one_call_site_per_wfp_call=pass
MS5 control: a second "Native.FwpmFilterAdd0(h, ...)" call                             -> one_call_site_per_wfp_call=FAIL
MS6 "new System .Net.WebClient()"                                                     -> namespaces=pass
MS7 a tracker reference glued after a letter ("x" + hash + four digits)                -> source_hygiene=pass (the repository lock
     research_tracker_lock.scan_bytes counts it: tracker-ref 1)
MS8 control: the same reference after a space                                          -> source_hygiene=FAIL
```

- **Why the scans miss:** the branch tracker does not recognise `#elif` (`NcoProbe.cs:2952-2954`), and the needles are exact substrings
  (`:2962`, `:2971`, `:3006`). The hygiene look-behind adds `\w`, which the repository lock does not (`:3010` against `research_tracker_lock.py:113`).
- **README overclaims.** The README (Guards and instruments) says "a source scan finds that every environment read outside the toggle branch is of
  the trace variable". The genuine source already reads the environment outside the toggle branch: `ProcessTest.RunChild` enumerates
  `psi.EnvironmentVariables` at `:2511-2513`. That read is benign (test-only; it removes `NCOPROBE_*` keys), but the sentence is false of the code.
- **Unbanked claim.** "Each of these scans was shown to fail on a tampered snapshot" has no test in the four files.
- **Why LOW:** the process-level rows independently show that the shipped exe ignores the two toggle variables (reproduced below), and the
  P/Invoke allowlist holds the import set. The scans are the weaker leg of that evidence.

### P1-7 LOW: after a run that leaves the filter behind, the next run measures something else, and nothing says so

- **Where:** fixed key `K.FilterKey`. `RUN_SHEET.md:45, 69, 76-85` say "repeat three times", with no instruction to stop on `filter_left_behind` or
  exit 8.
- **Concrete failure:** after an exit-8 run, the next add returns `FWP_E_ALREADY_EXISTS`. It is classed `other` (harness:
  `ClassifyAdd(0x80320009) => other`). That run's delete may remove the earlier run's filter, so the residue is attributed to the wrong run.
- **Hypothesis** (needs the engine). Two fixes are possible: the run sheet stops on exit 8, or the probe reads the key before the add and refuses
  when it is present (a SPEC amendment).

### P1-8 LOW: prose that does not match the code

- **The toggle comment is false.** `NcoProbe.cs:186-187` says the shipped build "contains neither variable name". The shipped exe contains both
  `NCOPROBE_TOGGLE_OFF` and `NCOPROBE_TOGGLE_STALE_SUBJECT`, from the `ProcessTest` constants at `:2372-2373` (byte search of the built shipped exe:
  present = True for both). Lines 26-27 and the README state this correctly.
- **The folder refusal names the wrong reason.** A folder given as `--live` is refused with "the proof file does not exist" (P02), because
  `FileInfo.Exists` is false for a directory. The Directory bit in the attribute test at `:863` is unreachable. The field (`live`) is right.

### P1-9 LOW (outside the four files, for the case-4 lead): directory-mode scrubbing would rewrite the fabricated stale SID as a machine SID

- **What is wrong:** `scrub_public_identifiers.py --dir` applies rule 4 to every `S-1-5-21-a-b-c-rid` SID, the fabricated stale-SID domain
  included. Tracked mode does not touch it in this folder: `SID_SCOPE` (`scrub_public_identifiers.py:93-97`) does not cover the nep0005 `runs/`, and
  the banked `runs/halfset-20261013-104631.json` and `runs/results-summary.json` keep the stale SID literally.
- **Concrete failure:** suppose Part 3 sanitises the case-4 record copies with `--dir`, as the copies hold `nco-probe`'s real machine SID. Then
  `filter.user_sid`, `filter.sd_sddl` and `stale_sid.sid` would read `S-1-5-21-__MACHINE__-91763`. The committed evidence would then say the filter
  named an account of this machine: the opposite of the design.
- **Reproduced** on a scratch copy of this review's first draft: `--dir --check` flagged it, and the rewrite produced
  `D:(A;;CC;;;S-1-5-21-__MACHINE__-91763)`.
- **Incidence:** none in the banked tree.

## Attacked and could not break

- **The arming interlock: 34 process-level refusal vectors on the shipped exe**, every proof carrying a wrong exe hash. All ended exit 3 (or 2 for
  usage) naming the expected field. The vectors were:
  - no `--live`, a folder, a missing file;
  - UTF-8 with BOM (parsed, then refused at the hash), UTF-16 (refused at `json`);
  - duplicate keys, including one spelled with a `\u` escape;
  - key case (`Schema`), a trailing space in a value;
  - exactly 1 MiB (refused), 1 MiB - 1 (parsed), 1 MiB + 1 (refused);
  - a symbolic link and a junction (refused); a hard link (read normally);
  - an alternate data stream, `NUL`, `CON` (no hang), a `\\?\` path (all refused);
  - a trailing NUL byte, a top-level array, the exe hash as a JSON number;
  - an empty file, a BOM-only file, a read-denied file;
  - `run` without `--out` (usage, before arming), a full-width `F`.
- **Boundaries at the pure level (fake hashes only):**
  - `written_utc`: exactly 24 h old is accepted and 24 h + 1 tick refused; exactly 5 min ahead is accepted and 5 min + 1 tick refused. This is the
    SPEC's reading.
  - Refused: no zone, lower-case `z` or `t`, a leap second, `24:00`, year 0, out-of-range results of `+14:00`/`-14:00`, `+14:01`, an 8-digit fraction,
    full-width digits, a comma fraction.
  - GUIDs: braces, surrounding spaces, the N and X forms, a NUL suffix, Unicode hyphens, a full-width digit, a sign or `0x` prefix are all refused.
    Upper case is accepted (the same GUID).
  - `checks_failed`: only the literal `0` passes.
- **The toggle mechanism.**
  - The shipped exe ignores `NCOPROBE_TOGGLE_OFF=interlock,stale_sid` and `NCOPROBE_TOGGLE_STALE_SUBJECT` (P22-P24 refused exactly as without them;
    `--version` unchanged, V5).
  - `--version` reports `toggle_build` false for the shipped build and true for the toggle build.
  - The toggle exe with no toggle variable keeps the interlock on (P33, P34).
- **The self-hash.** A copy under another name and a symbolic link to the exe both report the sha256 of the real bytes, with the invoked path
  recorded (V3, V4). The binding is to content, and `bin\` is admin-only for writes.
- **Constants and the security descriptor.**
  - Every constant matches the SDK headers and `spike-nep5-lib.ps1` (S2, provider, stale SID). The filter key is the SPEC's fixed key.
  - The descriptor is `D:(A;;CC;;;<the stale SID>)`: 64 bytes, control `0x8004` (self-relative, DACL present), no owner
    or group. That is the same form as the spike proven live.
  - The stale SID is unmapped here (1332).
- **Struct layouts.** Field for field identical to `wfp-coder-egress-spike.ps1`. Self-test asserts sizes 200/40/72 and every offset.
- **Behaviour locks have teeth.** Mutant MB1 (an extra Everyone ACE) fails `sd.parsed_back_names_exactly_the_stale_sid`. MB2 (0x80320003 to
  `denied`) fails `rc.classify_add`. MB3 (the `expected_account` check removed) fails both `expected_account` rows.
- **Standing rules.** None of the four files contains an account-lifecycle verb or API, a credential, a network or registry write, `runas`, a
  tracker reference, the operator's name or this machine's account-domain SID. The only pattern hits are comments that deny a capability. The
  repository tracker lock patterns count 0 in all four files.
- **The record seam (names only).** Every field the driver's `Test-C4Record` and `Get-C4RecordRow` read exists under that name in the probe's record.
  I did not run the driver against a real probe record.
- **Observation, no finding.** `display_name` accepts invisible and bidirectional-control characters (a lone U+200B passes "non-empty"; U+202E and
  U+2028 pass). The driver supplies the name from the library marker, so there is no exposure.

## What I ran (probe executions non-elevated through `run-limited.ps1`, with one exception)

Correction, made in round 2: the exception is item 8. The scan-mutant harness, an executable compiled from the probe source,
ran in the reviewer's elevated shell without a trace variable. It called only `ProcessTest.SourceScans` over text, by
reflection. Round 2 re-ran the equivalent harness non-elevated with a barrier trace and got the same verdicts on the round-1
forms.

`<scratch>` is the reviewer's session scratchpad under `%TEMP%`, outside any git tree. Every helper script lives there.

1. `run-limited.ps1 -SelfCheck`: **PASSED** (Medium label, Administrators deny-only, no High label).
2. `build-probe.ps1 -BuildDir <scratch>\build1`, with and without `-Toggle`. This ran csc only; the exe was not executed. The shipped exe was
   `8a0c27d2805c733a28e43047f15fd678422a7ba98e935ea215f5dde93d0a8226` and the toggle exe `bc212faf30fe662d5f287dab5f2834d4d06370b11c2d47cfeff2c005fa86303d`,
   both from source `52afc31f...`.
3. The author's runner through the launcher:
   ```
   run-limited.ps1 -Command 'set "NCOPROBE_ENGINE_OPEN_TRACE=<scratch>\tr\runner\nofolder\engine-open.trace" & pwsh -NoProfile -File "<nco>\probe\run-probe-selftest.ps1" > <scratch>\out\runner.txt 2>&1'
   ```
   Output: version.shipped PASS, version.toggle PASS, selftest 66/0, selftest-process 92/0, engine_open_trace_absent PASS; **checks_run 163 /
   checks_failed 0**. The runner's own builds were shipped `007f9493...` and toggle `799512d8...`.
4. A pure-function harness: the probe snapshot compiled with a reviewer entry point (`/main:`), calling only `Proof.Validate` with fake hashes,
   `Outcome`, `Sd`, `Args` and the lookups. It never called `Engine.Drive` or `RunCmd`. Rows U00-U10 are quoted above.
5. The process attack on the shipped exe: rows P01-P34, the `--version` rows V1-V5 and `identity` (I1), 40 children in all, each with stdin
   closed and a 20 s timeout.
6. The scrub test (P1-1) on a scratch copy of the `identity` output.
7. The repository's `research_tracker_lock.scan_bytes` and a standing-rule pattern scan over the four files.
8. Scan mutants MS0-MS8, through the probe's own `SourceScans` by reflection (text only).
9. Behaviour mutants:
   - MB1-MB3 compiled from copies, `selftest` only.
   - MB4 built with the author's `build-probe.ps1` from a scratch copy, then `selftest` and `selftest-process`.
   - MS3 compiled only, never executed.
10. `certutil -error 0x80320028`, SDK header reads, and greps of the driver, harness and run sheet.

Not run: the standing gate and pytest. Nothing here touches them; the four files were untracked during most of the review.

## Trace-file verdict, every invocation

I set `NCOPROBE_ENGINE_OPEN_TRACE` to a file inside a folder that does not exist, unique per invocation, rather than to a writable empty file. A
writable trace only shows an engine open after it happens. A barrier stops it: reaching the engine entry ends in exit 10 before the engine is
touched. The STOP rule fired on any exit outside the expected refusal set, any exit 10 or `trace_failed`, or the barrier folder appearing.

**Result: no invocation exited 10 or reported `trace_failed`.** No barrier file or folder was ever created. This was checked after each of the 40
attack children, the harness and mutant `selftest` runs, and the outer barrier of each of the 5 launcher sessions. The author's runner reported
`engine_open_trace_absent` PASS for its own barrier.

Inside `selftest-process`, the toggle rows write one line to their own writable trace by design. That build has no engine-open call (sentinel
`toggle_build_never_opens_engine`). Those lines come from the author's rows, not from my invocations, and are asserted by those rows.

No probe proof that could validate was written. Every fixture carries `probe_exe_sha256` = 64 x `a`, or a number, and no real exe hash was copied
into any file. `--live` was passed only with those fixtures and with paths that do not hold a proof.

## What I could not test

- Everything past `FwpmEngineOpen0`, by rule: real add and delete statuses, the read-backs, persistence, a record written after a real engine run, and
  whether `0x80320028` can occur for this filter (P1-2 incidence).
- The trigger of P1-3 (a throwing WFP call), and the P1-4 and P1-7 scenarios end to end.
- The suites under an elevated token. The SPEC has reviewers run non-elevated, but the driver's `-SelfTest` may run the runner elevated; that path was
  not exercised.
- Running under `nco-probe` (secondary logon, no loaded profile), the E elevation path, and the interactive `--wait` key press.
- The driver (B2) beyond the record field names.

## Merge read

- **Block live use on P1-1 and P1-2.**
  - P1-1 leaks personal data silently past every downstream gate. Only a change at the source closes it.
  - P1-2 is a one-line classifier fix, but its self-test, the SPEC amendment, the driver and the driver's self-test all assert the wrong mapping, so
    all of those move together.
- **Land P1-3 and P1-4 in the same round.** I would not block on either alone. Each is a one-place change. When either fires, the live record or the
  live session pays: a false `succeeded`, or a STOP in the middle of the ceremony.
- **P1-5 to P1-8 do not block.** They over-certify or misdescribe a design that, on the evidence above, currently holds.
- **P1-9 is a Part 3 decision.** It needs settling before the record copies are sanitised. It does not affect the live run.

Round 2 should re-run the runner and rows P01-P34, U00-U10 and MB1-MB4 at the fixed hash.
