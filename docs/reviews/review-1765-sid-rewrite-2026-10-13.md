# Adversarial review: #1765 SID-domain rewrite (feat/1765-sid-domain-rewrite @ dfd1d552, base 3a60fa81)

Reviewer did not write the code. Read-only on the branch; every claim below was run, not read. The machine's
real account domain is referred to as "the machine domain" and is written nowhere in this file. All pytest
runs used LOCALAPPDATA redirected to a scratch directory and the main checkout's interpreter
(`C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe`; the worktree has no venv). Clock: 2026-10-13 22:1x -04:00.

## Verdict: FAIL (one standing-gate break, two stale or residual leaks in publishable docs)

## Findings, most severe first

**1. HIGH. The rewrite silently invalidated an operator tool's pinned real-mode spec; 4 standing-gate tests fail on the branch and pass on main.**
`tools/operator/remove_codex_sandbox.ps1:123` pins `$script:RealSpecPin` = sha256 of `Get-RealSpec` (lines 148-177). The
byte rewrite changed five SID strings inside `Get-RealSpec` (lines 156-161) and left the pin, so every real-mode entry now
refuses at the FIRST gate (`spec-real-pinned`) instead of the gate the tests expect.
```
pwsh digest_check.ps1   (AST-extracts Get-RealSpec + Get-SpecDigest + the pin from each revision)
codex_base.ps1: pin=f6978245e05b...  computed=f6978245e05b...  match=True
codex_head.ps1: pin=f6978245e05b...  computed=8101e3215b86a5dbf12ad6d88d64b3893e8257ba914c64e8407a67a000bab951  match=False
python -m pytest tests/security/test_remove_codex_sandbox_static.py -q -p no:cacheprovider      (branch worktree)
  FAILED ...::test_guided_stage_two_is_refused_on_the_real_machine_in_any_letter_case[aclentries|ALL|AclEntries|all]
  E  assert 'not enabled for the real machine' in '...REFUSED[spec-real-pinned]: the allowlist is not the built-in real allowlist...'
  4 failed, 125 passed, 1 deselected
same command in C:/Users/mrbla/BlarAI at 3a60fa81 (main):  4 passed
```
Why this is not a one-line re-pin: the five strings were the REAL SIDs of the Codex sandbox accounts and group, which the tool
compares against live identities (`Assert-UserIdentity`/`Assert-GroupIdentity`, lines 937-949, gate `sid-match`) and uses
as the needles for finding their leftover ACEs (lines 252-258, 623, 814). With the placeholder in place, re-pinning would make
the tool run against an identity no account ever had, and the ACE scan would read "clean" for the real orphan ACEs (lenient
direction). No `CodexSandbox*` local user or group exists on this box today (`Get-LocalUser`/`Get-LocalGroup` returned none), so
the tool's real mode is historical, but the branch must decide and record one of: retire real mode (and its tests) with the
reason; re-pin and state in the file header that the recorded SIDs are placeholders and the live-match gate is therefore
inert; or keep real identity out of the tree by another design. The new lock forbids restoring the real values.
Incidence: this is the only tracked code file whose behaviour depends on the digits (the four bundled NEP-0005 files are
hash-booked, see below; `shared/tests/test_file_dacl.py` uses the constant only as a shape).

**2. MEDIUM. The unposted external draft still asserts the code carries the real domain and must be rewritten.**
The NEP-0005 evidence write-up (unposted), line 237: "The bundle's matrix code (`scripts/`) still carries
the test account's real SID domain. It must be rewritten with placeholder domains before any public push." False after this
branch; the README was corrected, this draft (the current one, last touched in 0fcefb45) was not. Brief item 5 asked for no
stale claim anywhere. Same sentence in the superseded v4 at line 86. The disposition and review records that mention the old
"Not yet scrubbed" section (`nep0005-branch-premerge-review-disposition-2026-10-13.md:26`,
`review-nep0005-branch-premerge-1763-2026-10-13.md:33,110`) are dated history and need no change.
```
git grep -n -i "still carries the test account's real SID domain" dfd1d552 -- .   -> 2 hits (line 86 of the superseded earlier version, line 237 of the NEP-0005 evidence write-up (unposted))
```

**3. MEDIUM. One third of the machine domain survives in a tracked, publishable review file, and no gate sees it.**
`docs/reviews/review-nep0005-branch-premerge-1763-2026-10-13.md:14` quotes a truncated SID `...-<third sub-authority>-1001` from
a test output. The rewrite needs all three numbers so it did not fire; the lock regex needs all three; the publisher
(`agentic-setup/scripts/publish-public-snapshot.ps1`) ships the whole tree and its private pattern file holds the full and
prefixed domain only (checked: 13 patterns, full domain present, single sub-authority absent). Pre-existing on main (1 hit at
3a60fa81), so not introduced here, but the ticket's purpose is the machine SID out of the tree and this is the last piece of
it. Incidence: 1 file, 1 occurrence; the first and second sub-authorities alone appear in 0 tracked files.
```
python bytecheck.py  -> part_a 0 [] | part_b 0 [] | part_c 1 ['docs/reviews/review-nep0005-branch-premerge-1763-2026-10-13.md']
```

**4. LOW. Lock regex swallows a domain preceded by `<digits>-` into the previous token (undocumented miss).**
`tests/security/test_no_machine_sid_domain_in_tree.py:36` `DOMAIN_RE = \d{1,10}-\d{1,10}-\d{1,10}` with `finditer` is
left-greedy; the HONEST LIMIT paragraph does not list this shape. Reproduced with the production function and a fabricated
pinned domain:
```
prefixed  S-1-5-21-D-1001          -> caught 1
5-D-1001                            -> []        (token read as 5-a-b, then c alone)
S-1-5-21-5-D-1001                   -> []
9D-1001 with 9-digit parts          -> []        (n/a for this machine: all three parts are 10 digits, so a glued lead digit cannot absorb)
trailing glued digit, CRLF after prefix, 10-digit glued lead -> caught
spaces around dashes, fullwidth digits, en-dashes, UTF-16   -> [] (declared limits)
```
Incidence in tree: 0 (the tree grep for the bare domain is 0 in every form). Report only; a tokeniser over runs of
`[\d-]` checking every 3-window, or a `(?<![\d-])` guard, would close it.

**5. LOW. `docs/security/DATA_MAP.md:237` now states "this box is `1000000001-1000000002-1000000003`".**
A false statement about the live machine in a security data map with no cue that it is a placeholder (the README's
convention note lives in the bundle, not here). Reword to say the box's domain differs and is redacted.

**6. NOTE (not a defect). The script replaces glued digits**: `91234-5678-90123` became `91000000001-...-10000000033` in the
scratch repo. A SID sub-authority is at most 10 digits, so a glued match is never a valid SID; in the scrub direction
over-matching is the safe side. Binary files are reported and the rewrite exits 1 (fail-loud), untracked files untouched.

**7. NOTE. Branch `feat/trackb-1753-residuals`**: its bundle-test hunks (466, 544, 571, 699+) do not overlap this branch's
(3, 47, 80, 92, 243, 681). But trackb carries the machine domain in 82 files, the bundle test included, in lines this branch
rewrote: merging trackb after this one will conflict there and will reintroduce the domain anywhere trackb alone changed a
carrying line. The lock will fire on main; whoever merges trackb must run `scripts/rewrite_sid_domain.py --check` first.

## What was verified and could not be broken

- **Claim 1 (87 files / 918 occurrences, digits only).** For every changed file except the five hand-edited ones, old blob with
  domain→placeholder substituted equals the new blob byte for byte: 86 files, 915 occurrences, 0 mismatches; the bundle test
  held the other 3 (hand-edited) = 87 / 918, equal to the log header. Tree grep on the branch: 0 ASCII, 0 UTF-16 LE/BE, 0
  `a-b` or `b-c` pairs; docs/archive is tracked and included. Unchanged as required: orphan `76345465-…` 10/10 hits
  base/head, Codex capability domains `2312800277-…` 2/2 and `2620682446-…` 2/2. Distinct prefixed domains left on the
  branch: placeholder 1770, fabricated `17630000-…` 135, `1-2-3` 58, `1111111111-…` 51, `9-9-9` 22, orphan 9, and test-only
  shapes. `--check` on the worktree: "0 tracked file(s)", exit 0.
- **Claim 2 (script).** Scratch git repo with a fabricated domain: CRLF kept (2 CRLF before and after), BOM kept, SDDL JSON 3/3
  replaced, lower-case prefix and split-after-prefix handled (bare digits), untracked file untouched, NUL file skipped and
  reported, exit 1. `--domain` = placeholder → exit 2; `12-34`, `S-1-5-21-1-2-3`, 11-digit part, bad `--placeholder` → exit 2;
  rewrite without `--log` → exit 2. Second run: 0 files, same tree (idempotent). Log never contains the domain. `--check` with
  a planted domain → exit 1.
- **Claim 3 (lock).** `git clone --no-local` of the worktree at dfd1d552, planted the machine domain in a tracked JSON (prefixed)
  and a tracked txt (bare): `1 failed, 4 passed`, both files named. Same files untracked: `5 passed`. On the branch: 5 passed,
  0 skipped (`-rs`). DIGESTS entry == sha256 of the live bare domain (recomputed in pwsh). Live read works through `pwsh` and
  `powershell`; with `pwsh` failing the fallback reads it; with both failing the function returns None and the readability
  test FAILS on win32 (does not skip). Full scan 3973 tracked files in 1.79 s. Toggle tests call the production
  `offending_files`. Lock reaches every form FULL_SID_RE catches (FULL_SID_RE is prefix-only; the lock is bare-digit).
- **Claim 4 (bundle test).** `sid_allowed_here`/`SID_SCAN_EXEMPT` absent (grep); the four former-exempt paths each get a
  real-looking domain case; the allowed-domain set is unchanged (no widening). Targeted run: `tests/security/
  test_containment_evidence_bundle.py tests/security/test_no_machine_sid_domain_in_tree.py shared/tests/test_file_dacl.py`
  → **129 passed, 0 skipped, 75.8 s**.
- **Claim 5 (hash bookkeeping).** LF-normalised sha256 at 3a60fa81 and dfd1d552 for halfset.rs (e0d560fc… → cbd6ad65…),
  refusals.ps1 (fe867945… → 11b49f47…), spike-nep5-lib.ps1 (50325acc… → 56b6418d…), connect-probe.ps1 (545333e5… →
  eccfd60b…) equal AS_RUN.md, the matrix JSON note, and the rewrite log. `make_changes.py --check` → "up to date", exit 0.
  README section 34-41 is true. CHANGES.md rows show the new SID-replacement counts (3/1/1/2).
- **Security read.** The bundle scan lost its only exemption and gained no allowed domain: a strengthening. The lock is
  fail-loud when it cannot read its subject. No control was weakened except as finding 1 records (an operator tool's
  identity gate now refuses everything, which is the closed direction, but by accident and with a test break).

## Merge read

Block on finding 1 (gate break plus an undecided semantics change) and finding 2 (false statement in the artifact that
will be posted). Finding 3 should land in the same branch: it is one line and it is the ticket's goal. Findings 4-5 can be
ticketed with a `blocked-by:` predicate. Suites run at dfd1d552: the three targeted files (129 passed), the codex static test
(4 failed / 125 passed; 4 passed on main 3a60fa81), the lock on a planted clone (fails as it should). Standing gate not run.
