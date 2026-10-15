# Adversarial review round 2: #1765 SID-domain rewrite (feat/1765-sid-domain-rewrite @ 8a41150c, base 3a60fa81)

Reviewer did not write the code; read-only on the branch. Fixes under review: a8da5b1f, 8a41150c (`git diff dfd1d552 8a41150c`).
Every claim below was run. The machine's real account domain is called "the machine domain"; it and its three numbers
appear nowhere here. pytest ran with LOCALAPPDATA redirected to scratch and `C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe`.
Clock 2026-10-13 22:44 -04:00 at start. Session elevated. Scratch clones holding planted fixtures were deleted after use.

## Verdict: FAIL (one blocking item: the Codex tool's new header misstates what its scans still cover)

## Findings, most severe first

**1. MEDIUM, blocking. The re-pin comment claims coverage the tool no longer has, in the lenient direction.**
`tools/operator/remove_codex_sandbox.ps1:63-69` says "the SID-based scans for those three identities find nothing and the
name-based scans still run"; `:135-138` says the scans of "access lists, filters, tasks and rights ... report by NAME only
for those". Both wrong where it matters. Once an account is deleted its name stops resolving, so residue such as
user-rights entries, filter conditions and access entries can only carry the SID. The access-list scan (Get-ScanSids,
Find-SidAcesDeep, Write-TreeSnapshot's 'scan-only-sid' refusal) has no name path at all. Same input, pure functions
AST-extracted from each revision, machine domain read live:
```
[main-3a60fa81]   rights hits for a deleted account and group written as raw SIDs: 2
[main-3a60fa81]   wfp hits for a filter scoped to the deleted account's SID: 1
[branch-8a41150c] rights hits for a deleted account and group written as raw SIDs: 0
[branch-8a41150c] wfp hits for a filter scoped to the deleted account's SID: 0
```
Cost when it fires: `-Verify` is not blocked on the real machine for any stage. Only the Stage 2 apply is refused, at
`:1563` and `:2423`. So a future "is Codex fully gone" check returns clean while residue of the deleted group stays, and
the header tells the reader the name scans cover it. Three comments became stale in the same way: `:263-265` (the deep
scan "refuses to start when it finds one" for account and group entries), `:271-272` (rights matched by SID and name),
and `:69` ("Stage AclEntries looks for Codex's capability SIDs", which drops the account and group SIDs it also refused on).
Incidence today is zero, measured elevated, counts only. The user-rights export holds 0 entries for the three deleted RIDs.
The filter export (3.56 MB) holds 0 such entries and 0 hits on the three filter needles. Scheduled tasks with those
principals: 0. Access entries across a 592-object sample of the five roots: 0. Nothing is lost on the box today. The
defect is a security tool's contract comment that says otherwise, which principle 11 (fail-loud) does not allow.
Fix shape (author's call): say plainly that for the three deleted identities every scan is blind, so a clean Verify is
no evidence about their residue.

**2. LOW. The journal fragment contradicts the records it summarises.**
`docs/journal_fragments/2026-10-13_1765-sid-domain-rewrite.md`, paragraph 4, says round 1 "failed it on two things" and
that the second was the truncated quotation. Round 1 blocked on findings 1 and 2: the pin and the stale draft sentence
(`review-1765-sid-rewrite-2026-10-13.md` merge read; the disposition says "FAIL on R1 and R2"). The quotation was finding 3.
Paragraph 5 says "about twenty untracked review hand-backs in the main checkout carry the domain today". Measured now:
```
untracked 48  full-domain 2  any-number 2  utf16-full 0      (main checkout, git ls-files --others --exclude-standard)
```
The figure comes from the gate hand-back's estimate ("About 20 untracked files", `HANDBACK_gate-1765-...md:25`) and was
not re-measured. Main has not moved (3a60fa81), so none were committed in the meantime.

**3. LOW. The lock's docstrings misdescribe what it catches, in both directions.**
`tests/security/test_no_machine_sid_domain_in_tree.py:24-25`, the HONEST LIMIT, says the lock cannot see a domain split
across lines or numbers separated by anything but a dash. The per-number digests catch all of those. It does not list a
shape that is missed: a number glued to more digits. Production function, fabricated pinned domain, production digests:
```
spaces a b c=3   split across CRLF=3   dotted=3   en-dash=3   %2D=3   double dash=3     (claimed unseen; caught)
9a alone (11 digits)=0   0a-0b-0c=0   1a1-1b1-1c1=0   UTF-16=0   fullwidth=0          (missed)
near miss, one digit changed: windows-only=0, production=2
```
The toggle docstring (`:120`) says a near miss is "not caught". Its row (`:132`) runs without the per-number digests, so
it certifies a configuration the gate never uses; in production the near miss is caught twice, which is correct. `:20`
says "every run of ASCII digits and dashes is one token", but `a--b-c` splits. No crash path was found. Leading dash,
trailing dash, dash-only runs, empty input and short tokens are all handled. A 200,000-part token took 0.09 s.
Incidence of the missed shapes: 0. A substring grep for each number over the branch tree gives 0 files each, UTF-16 0.

**4. LOW. The lock tells the operator to use a tool that cannot see one of the shapes the lock now fails on.**
The failure message at `:114` says "rewrite with scripts/rewrite_sid_domain.py". In a planted clone the lock named all
three plants; the script's check saw two of them and missed the lone-number fragment:
```
lock:    plant_i_prefixed.json: 4 | plant_ii_one_number.md: 1 | plant_iii_glued.txt: 4      1 failed, 5 passed
script:  carries the domain (1): plant_i_prefixed.json | carries the domain (1): plant_iii_glued.txt   exit 1
```
Disposition row R7 names the script's check, the weaker instrument, as the predicate for merging #1753. The lock is the
stronger backstop and should be named.

**5. NOTE. The header names the second lock as the refusing gate.** On the apply path a recreated `CodexSandboxOffline`
is first refused at 'unexpected-live' (`:1570`, a finding that the SID differs from the recorded one); 'sid-match' is the
next independent lock. Both refuse, as driven from the branch. Firewall entries also carry the placeholder, so a recreated
rule refuses at 'fw-identity'. That is the closed direction, and the header does not mention it.

**6. NOTE.** `offending_files(..., sub_digests=frozenset())` defaults to a weaker lock. The only production caller passes
the digests.

**7. NOTE.** Scan time over 3976 tracked files, three runs each, other agents active. It does not matter for the gate.
```
new: 2.95 / 2.96 / 2.89 s     old algorithm: 1.54 / 1.35 / 1.33 s     whole test file: 4.1 s
```

## What was verified and could not be broken

- **R1 pin.** AST-extracting Get-RealSpec and Get-SpecDigest recomputes the pin `8101e321…` exactly. All five account,
  group and firewall SIDs carry the placeholder with RIDs 1006-1008. The static suite passes: 129 passed, 1 deselected,
  40.4 s. The self-test's pure real-spec checks were evaluated on the branch spec: pin equal, digest stable, scan set 6,
  purge set 2, 2 with the lock off. The pin check at `:1811` would pass. The self-test has no check tied to the live domain.
- **R1 closed direction and live box.** For a recreated account, sid-match and the group check both refuse, and a finding
  is raised. There are 0 Codex users, 0 Codex groups and 0 codex firewall rules, which matches #1743 comment 4058. The
  real RIDs 1006-1008 and the placeholder SIDs do not resolve (IdentityNotMapped). Live local RIDs run to about 1960. A
  placeholder can match only an entry someone writes on purpose, and the ACL sample holds 0.
- **R2.** The phrase now appears once, in round 1's quoted command, which is history. Line 237 of the NEP-0005 evidence write-up (unposted) and line 86 of its superseded earlier version are true. At
  3a60fa81 the domain sat in harness/ (4) and scripts/ (3); srtcli/ and runs/ held 0.
- **R3/R4.** DIGESTS and each SUB_AUTHORITY_DIGESTS entry equal the sha256 of the live domain and of its numbers, with
  the comment labels correct. The branch lock passes 6 of 6 with 0 skipped. In a planted `git clone --no-local`, all three
  tracked plants fail the lock by name; the same plants untracked pass 6 of 6. On the branch each number alone appears in
  0 files.
- **R5.** DATA_MAP.md:236-237 is true and plain.
- **R7.** Merging feat/trackb-1753-residuals (tip b0ac7a1d) onto the branch in scratch gives 4 conflicts. The same 4
  occur against main alone, so this branch adds none. On the conflicted result the script check reads 0 files and the lock
  passes 6 of 6. A whole-file "theirs" for the 4 conflicted files carries 0. The zero can disagree: the trackb tip alone
  carries the domain in 82 files, main 87, the branch 0.
- **Other checks.** The script check on the branch reads 0 files, exit 0. `make_changes.py --check` reads up to date.
  `verify_disposition.py` passes 13 of 13. The journal's halfset.rs hashes e0d560fc and cbd6ad65 match the LF hashes.

## Merge read

Block on finding 1: rewrite the header and the three stale comments so they say what the scans can no longer see. That is
prose only and needs no code change; the static suite does not read it. Findings 2 to 4 are small truth fixes and
belong in the same pass. Findings 5 to 7 need no action. Suites run at 8a41150c: the Codex static suite (129 passed),
the whole-tree lock (6 passed), the lock in a planted clone (1 failed, 5 passed, as designed), in an untracked clone
(6 passed) and on the #1753 scratch merge (6 passed). The standing gate and the Codex self-test were not run.
