# MXC denied-subtree probe: pre-run adversarial review, round 5 (2026-10-15)

Target: branch `feat/mxc-denied-subtree`, commit `b1cb40e3` (diff against round-4 `bd3694d6`: `landing.py`, `run_probe.py`, `summarise.py`, `self_test.py`), working tree clean against the commit. Spec: the CASE_2 mxc-denied-subtree file of 2026-10-15 (read only). Round-4 fixtures re-used from round 4's scratch, copied to `%TEMP%\claude\...\scratchpad\mxr5\` with the tree root changed to `C:\mxc-fx-review5` and one new fake mode (`foreign`).

**VERDICT: no BLOCKER or HIGH in the code at `b1cb40e3`. APPROVAL NOT WRITTEN: the one self-test run did not complete.** It aborted on a 600 s subprocess timeout in its third end-to-end case while the box carried the standing gate plus this reviewer's three parallel fixture runs. 148 checks printed PASS and none printed FAIL before the abort. The remaining 14 end-to-end locks, including the new hiddenland, lockafter-noreport and smoke-cause locks, did not run under the self-test. `APPROVED_SHA256.txt` (round 3, `42fd5f1c`) is untouched, and no `.round3.txt` copy was made. One complete self-test run at `b1cb40e3` on a quieter box is the only thing between this review and an approval.

## What was run, at b1cb40e3

All of it ran under `run_nonelevated.ps1` at Medium integrity.
- `self_test.py`, once, started 21:45 UTC. 148 PASS and 0 FAIL lines, then `subprocess.TimeoutExpired: ... run_probe.py --out-root ...\e2e-nopayload-5 ... timed out after 600 seconds` (`self_test.py:847`, `run_e2e(scratch, "nopayload")`). The runner reported exit code 0 for this run. That is the runner's own status, and a reader must not take it as the self-test's result (finding 3).
- `attack5.py`: round 4's `attack4.py` cases A to E, plus three new foreign-entry cases F to H. Each holds the entry without read sharing at the after-snapshot where stated. Each runs through `landing.judge` and `summarise.verdict`.
- `e2e4.py` with `fake4.cmd`/`fake4.py`, which drive the real `run_probe.main` with no container. Modes: `hiddenland`, `hiddenland_report`, `foreign` (new), then `open` and `lockafter` re-run serially. The first parallel attempt at those two hit the 300 s `Get-AuthenticodeSignature` timeout (finding 2).
- `verd4.py` (the smoke-record verdicts).
- Not run: certutil hashing, `launch.ps1 -CheckOnly` (approval withheld), any container launch, any port bind.

## Round-4 findings

| R4 | Severity | Status at b1cb40e3 | Evidence |
|----|----------|--------------------|----------|
| 1 | HIGH | **FIXED** | The unit cases and the real `run_probe` both give FAIL wherever round 4 gave INSTRUMENT-BLIND or LAUNCH-FAILED. A: create, held, report → FAIL. B: create, held, no report → FAIL, `disagreements ['create_file']`. C: rename destination held, no report → FAIL, `landed ['rename']`. D: mkdir, unlistable, no report → FAIL, `landed ['mkdir']`. e2e `hiddenland`: `STOP: FAIL condition met (T/sub changed: ['sub/s2_new.txt']; container report absent)`, `VERDICT: FAIL`, `landed ['create_file']`, `read_errors ['sub/s2_new.txt']`, tree kept. e2e `hiddenland_report`: FAIL, with the disagreement now named in `blind_reasons`. The self-test now has a toggle lock ("with the unreadable entry dropped from the after-snapshot the landing is missed"), which is the discriminating split round 4 asked for. It printed PASS before the abort. |
| 2 | MEDIUM | **FIXED** | Case E (marker appended, held, no report): `VERDICT INSTRUMENT-BLIND`, `blind ["fx-a-r1: no container report and unreadable entries ['sub/marker.txt']"]`. `run_probe.py:368-370` now prints a stop line that names the read error, not "T/sub unchanged". e2e `lockafter` (report present, marker held): `STOP: the host could not read what it judged (instrument blind)`. The self-test's e2e no-report variant (`lockafternoreport`) did not run in the aborted self-test. The unit verdict lock "a launch with no report and a host read error is INSTRUMENT-BLIND …" printed PASS. |
| 3 | MEDIUM (spec owner) | unchanged, recorded | Not a code item. It still needs the ruling line in the case file or register. |
| 4 | LOW | **FIXED** | `verd5.txt`: `smoke changed MXC state -> STOPPED-STATE-CHANGE`. The verdict now has its own label, and `summary.json` gets `smoke_state_changed`. |
| 5 | LOW | **FIXED** | Smoke records now carry `cause` (`payload-import-failure`, `launcher-timeout`, `no-report`), and the stop text names it. The `summarise.py:15-18` LAUNCH-FAILED prose now covers a watchdog kill and a launcher timeout. A launcher timeout is still labelled CONTAINER-PAYLOAD-BROKEN (`verd5.txt`), but the cause field now separates it, which is what the finding asked for. |
| 6 | LOW | **FIXED** | The dead `if False` line is gone (no match at the hash). The new `tiermeasured` fake mode (smoke tier matches, measured dry-run differs) reaches `run_launch`'s own mismatch branch. That lock is at `self_test.py:870`, after the abort point, so it did NOT run this round. |

## The appeared/vanished rule against benign host-side entries

**Behaviour, reproduced.** Any entry that appears in, or vanishes from, a successful listing of `T\sub` is a change, so the run is FAIL. That holds whatever the entry's name, and whether or not the host can read it. A foreign entry gives FAIL with no named attempt landed:
- F, `desktop.ini` readable, report says all refused: `VERDICT FAIL changes=[('fx-a-r1', [], ['sub/desktop.ini'], 'report')] blind=[]`.
- G, `Thumbs.db` held: FAIL, `blind` names the unreadable entry.
- H, `~bdtmp.tmp`, no report: FAIL.
- e2e `foreign` (real `run_probe`, a third party writes `sub\desktop.ini` after the payload reported all five refused): `STOP: FAIL condition met (T/sub changed: ['sub/desktop.ini']; container report present)`, `VERDICT: FAIL`, `landed []`, `SUMMARY FAIL [['fx-a-r1', [], ['sub/desktop.ini'], 'report']]`.

This is not new at `b1cb40e3`. A readable foreign entry was already FAIL at every earlier hash. Round 5 adds the unreadable foreign entry.

**Is it plausible on this host?** No such entry has been observed. The live run's tree (`C:\mxc-fx\run-20261015-1\fx-a-r1\T\sub`) has sat on disk for about 5.5 hours with Bitdefender active. At 22:00 UTC, `dir /r /a` showed exactly the three fixture files and no alternate data streams. The mechanisms are unlikely within a launch window of a few seconds on a path nobody browses:
- Windows writes `desktop.ini` only when a folder is customised.
- `Thumbs.db` is not written for local folders on current Windows (the thumbnail cache is central).
- Antivirus products keep their temporary files in their own directories.

All of that is reasoning, not measurement, beyond the one 5.5 h observation.

**Which direction the spec requires.** The spec's FAIL clause names S2 effects: "a new file exists, the marker's bytes changed, a rename or delete took effect, a subdirectory exists". It routes a FAIL to Blair first, before any Microsoft report. FAIL therefore sends nothing on its own, and the cost of a false FAIL is one wrong verdict, which a human inspects against a kept tree. A false HOLD would be published as a measurement, which costs more. Downgrading an unattributed entry to INSTRUMENT-BLIND would be the wrong direction. The probe cannot prove which process wrote an entry. An unexpected name in `T\sub` while the policy was in force is still evidence that the deny did not hold for some writer, and a blind verdict would hide it.

**The one correct mitigation** (finding 1 below): keep the FAIL and the stop. Also make the attribution visible in the verdict line and the stop line: "FAIL (unattributed: no named attempt landed; changed: [...])". That way, before any routing, Blair sees that the change matches none of the payload's five attempts. The data already exists: the judge's `unattributed_changes`, and the empty attempt list in `summary.json`'s `changes` tuple. Only the human-facing line flattens it.

## New findings

### 1. LOW: a FAIL made only of unattributed changes reads the same as a real bypass in every human-facing line
- **Where:** `summarise.py:160-162` (the verdict is plain `FAIL`), `run_probe.py:365-367` (the stop text), and `landing.py:247-250` plus `:282` (`unattributed_changes` is computed and then used by no verdict or stop line).
- **Scenario:** a benign or third-party entry lands in `T\sub` during a launch. The console, `summary.json`'s `verdict` and the stop line all say FAIL. The only clue is `landed []` / `[]` in the tuple. The spec routes any FAIL toward a Microsoft report, with Blair told first.
- **Reproduced:** yes, e2e `foreign` above (`e2e5.txt`).
- **Incidence:** 0 banked, and 0 over about 5.5 h on the kept live tree.
- **Why not higher:** the FAIL still stops the run, keeps the tree, and sends nothing automatically. The record and the stop line name the path (`desktop.ini`), so the inspection Blair does before any report would find it.
- **Lock gap:** the self-test has "verdict FAIL on a change in T/sub no named attempt explains" (PASS), which locks the direction. No lock checks that the human-facing line marks the change as unattributed.

### 2. LOW: the launcher-signature read has a 300 s timeout that crashes `run_probe` with a traceback and no record
- **Where:** the `Get-AuthenticodeSignature` subprocess (`fixtures.py`, launcher identity collection), which `run_probe` calls before any launch.
- **Reproduced:** yes, once and under load. e2e `open` and `lockafter` in the first parallel batch each ended `rc 1` with `subprocess.TimeoutExpired: ... Get-AuthenticodeSignature ... timed out after 300 seconds`. Re-run serially, both completed: `open` gave FAIL with all six paths, and `lockafter` gave INSTRUMENT-BLIND.
- **Cost:** it fails loud and runs no launch, so the verdict cannot be wrong. On a loaded box the live run can end with no record of why. Its incidence on a quiet box is 0.

### 3. LOW (instrument outside the probe): `run_nonelevated.ps1` reports exit code 0 for a child that died with a traceback
- **Where:** `%USERPROFILE%\blarai-research-data\_tools\run_nonelevated.ps1`.
- **Reproduced:** the self-test aborted with an uncaught `TimeoutExpired` and no closing tally, and the background task still reported "completed (exit code 0)".
- **Cost:** an orchestrator reading the runner's exit code would take an incomplete self-test as green. Read the self-test's own final tally line, never the runner's code. The aborted self-test also leaves its `%TEMP%\mxcds-selftest-*` scratch behind; 32 such directories exist from this and earlier rounds.

## Attacked and could not break

- **Unreadable landed entries:** create, rename destination and mkdir, with and without a report, and through both the unit judge and the real `run_probe`. Every one gives FAIL. None gives LAUNCH-FAILED or INSTRUMENT-BLIND.
- **An unreadable entry present in both snapshots:** compared by kind only. It produces no change and no FAIL (case E). The round-3 false-FAIL direction stays closed.
- **No report plus a read error:** INSTRUMENT-BLIND with a named reason, never LAUNCH-FAILED. The stop line no longer says "T/sub unchanged" when a read failed.
- **Kind evidence for an unreadable entry:** `kind` comes from the directory listing (`scandir`), not from the failed stat or read, so a held file keeps `kind: file`. No path turns an unreadable entry into a kind change.
- **Smoke verdict precedence:** STOPPED-STATE-CHANGE ranks below FAIL and CONTAINER-PAYLOAD-BROKEN and above everything else, and it is reported with the change.
- **Hygiene:** no `__pycache__` in the probe directory after any run, and every reviewer tree under `C:\mxc-fx-review5` is gone.

## Merge read / run read

Nothing in the code blocks the run. Findings 1 to 3 are record-quality items. Finding 1 is worth doing before the live run because it costs one line of text and protects the routing decision, but it does not block.

The approval is withheld only because the self-test is incomplete at this hash. Run `self_test.py` once to its closing tally on a box not carrying parallel fixture runs. If the tally shows 0 failed, the hash-and-approve step can proceed at `b1cb40e3` on this review's findings.

Suites run by this reviewer at `b1cb40e3`, all non-elevated:
- `self_test.py`: aborted after 148 PASS and 0 FAIL.
- `attack5.py`: cases A to H.
- `e2e4.py` with `fake4`: `hiddenland`, `hiddenland_report`, `foreign`, `open`, `lockafter`.
- `verd4.py`.

Outputs are in `%TEMP%\claude\...\scratchpad\r5_selftest.txt` and `...\mxr5\{attack5,e2e5,e2e5b,verd5}.txt`.

## Addendum: complete self-test and approval (2026-10-15, after the standing gate finished)

- **Self-test, once, quiet box, no parallel fixture runs**, under `run_nonelevated.ps1` (Medium Mandatory Level). It ran from 22:26:49 to 22:30:08 UTC and closed with **`167 passed, 0 failed`**. Token line: `guarded privileges enabled before secure_token []; after []`. The locks that did not run in the aborted run all printed PASS. They are the e2e hiddenland checks with and without a report, the marker-held checks with and without a report, the measured-tier mismatch, the smoke state change and the smoke no-report cause.
- **Verdict: PASS** (no BLOCKER or HIGH). Findings 1 to 3 above stay LOW and are open.
- **Hashes** were taken under the runner with `certutil -hashfile ... SHA256` and cross-checked with `sha256sum`; they agree. The working tree was clean against `b1cb40e3` for `tools/`, and the directory holds 8 entries, with no `__pycache__`.
- **Approval:** the round-3 file was kept as `%USERPROFILE%\blarai-research-data\mxc-denied-subtree\APPROVED_SHA256.round3.txt` (header `commit 42fd5f1c ... round 3`). The new `APPROVED_SHA256.txt` has the header `# approved 2026-10-15T22:30:40Z commit b1cb40e3 reviewer non-elevated round 5` and 8 lines.
- **`launch.ps1 -CheckOnly` under the runner:** `hash check passed for 8 scripts`.
- **Cleanup:** the 33 `%TEMP%\mxcds-selftest-*` directories were deleted (none left). No self-test or run_probe process was running at the time.
