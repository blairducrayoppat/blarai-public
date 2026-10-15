# nono on the WSL 9P mount: does the sandbox fail open? A control, 2026-10-14

Ticket #1755, follow-up to nolabs-ai/nono#2089. Operator of both runs: agent (the Lead Architect's own run, which the ticket also asks for, has not been made).

## Purpose

nono builds a Landlock sandbox from the grants on its command line. #2089 recorded a set of cases on the WSL 9P mount (`/mnt/c`) in which the sandbox denied MORE than the grants allow (a fail-closed fault: a usability bug). The ticket records that nono's own source comment says Landlock rules on 9P "are accepted by the kernel but silently have no enforcement effect", which would be the opposite fault (fail open), and that #2089 never tested that direction. nono also prints, on every run on this mount, a warning that "grants may be silently ignored or incompletely enforced". The question this control asks: on 9P, can a sandboxed process do something its own command line does not grant?

Each probe is judged against what the command line grants, and success is read from outside the sandbox afterwards. A denied operation that succeeds would be a POLICY_VIOLATION and would go to nono's private advisory form, not to a public post.

## Result in one paragraph

No operation that the command line does not grant succeeded: 0 POLICY_VIOLATION in 360 runs. Of the 240 runs whose policy denies the operation, 222 were denied and 18 were not judged (see "The 24 runs not judged"). Every write outside the grant that was judged was denied 3 of 3 in all four cases: by plain path, through a junction, through directory symlinks with a relative and an absolute target, through file symlinks with a relative and an absolute target, by `..` traversal, in upper case and in title case, by 8.3 short name, by a colon-named entry, and by a hard link of an ungranted file into the grant (12 probes, 144 runs). Reads and listings of ungranted places were denied wherever the policy denies them, through every link and spelling (78 of 78 judged runs, cases A and C). The #2089 over-denials reproduce: operations inside the grant were denied in cases A and D (list), A, B and D (write), and worked in full only when nono was started inside the grant (case C). In case D the read grant on the parent folder gave no read of the ungranted sibling (every read and listing there was denied), while the read grant on the whole mount (case B) did. The upper-case spelling of the granted file was denied in A, C and D, so a grant matches the path as spelled; that is the fail-closed direction. Every denied run shows the command's own kernel error: `Permission denied` in 219 of the 222, and `Invalid cross-device link` in the three hard-link runs of case C (the error a refused cross-directory link gives). All 222 also carry nono's closing text "No path denials were observed during this session", so nono's own denial report does not see these denials on this platform; the evidence is the command's error and the absence of the effect, not nono's report. This is a finding about these 30 operations in these four configurations on this machine. It is not a claim that nono is secure on 9P.

## Conditions

| Item | Value |
|---|---|
| When | 2026-10-14, local evening (EDT, UTC-4): run 1 at 23:10, run 2 at 23:18 (2026-10-15 03:10 and 03:18 UTC) |
| Machine | Intel Core Ultra 7 258V laptop, Windows 11 Pro 10.0.26200; WSL 3.0.3.0; WSL VM 4 GB, 4 processors, mirrored networking (`.wslconfig`) |
| Kernel | 6.18.54.1-microsoft-standard-WSL2; Landlock ABI 7 (syscall query); the Linux security-module list file was not readable and is recorded as unreadable |
| Distribution | Ubuntu 24.04.5 LTS, Python 3.12.3, running as root (uid 0) |
| nono | 0.79.0 at `/usr/local/bin/nono` |
| `/mnt/c` | `9p rw,noatime,aname=drvfs;path=C:\;uid=0;gid=0;symlinkroot=/mnt/,cache=0x5,access=client,msize=65536,trans=fd` (file-descriptor numbers omitted) |
| Antivirus | Bitdefender present: `bdredline`, `discoverysrv`, `productagentservice`, found by image name and by process company in both the Windows and the WSL view |
| stdin of run 2 | piped, so nono skipped its working-directory prompt non-interactively (270 of 360 runs print "Skipping CWD prompt"; the 90 runs of case C start inside the grant and have none) and the post-run review menu never opened |
| Other load | three review agents were running on the host, as reported by the coordinating session; not measured here. Run 2 took 137 s for 360 runs (0.25 to 2.32 s each) |
| Fixture | `C:\wsl\p1755-run1`, prepared from an elevated shell (Developer Mode off): a junction, two directory symlinks, four file symlinks inside the granted folder, all pointing at an ungranted sibling and all verified from Windows; a long-named sibling with 8.3 names `UNGRAN~1` and `SECRET~1.TXT`; an NTFS stream; case-insensitive on the Windows side |
| Script | `tools/probes/nono_9p_failclosed_control.py` at commit `7da29183`; both runs record the SHA-256 of the bytes that ran, `b7cc9a6a53089ffdfc68b82ac3b5f2bad87f3eff6940d44da143939c44536302` |
| Controls | each probe also ran once outside nono: 29 of 30 succeeded (ADS_R did not, see below) |

The four cases, each started from `/root/work` except C:

| Case | nono command line | #2089 step |
|---|---|---|
| A | `--allow <fixture>/leaf` | 4 |
| B | `--read /mnt/c --allow <fixture>/leaf` | 6 |
| C | started inside `leaf`, `--allow .` | 7 |
| D | `--read <fixture> --allow <fixture>/leaf` | 5 |

## Verdicts, 30 probes by 4 cases, 3 runs per cell

Letters: D denied as policy, A allowed as policy, O over-denial (the policy allows it, the sandbox denied it), I inconclusive; the number is how many of the 3 runs. The policy column is what the command line grants in cases A B C D. Copied from `runs/run2-piped-20261014-231822.json`.

| probe | policy A B C D | A | B | C | D |
|---|---|---|---|---|---|
| W_OUT | deny deny deny deny | D3 | D3 | D3 | D3 |
| R_OUT | deny allow deny allow | D3 | A3 | D3 | O3 |
| W_IN | allow allow allow allow | O3 | O3 | A3 | O3 |
| L_IN | allow allow allow allow | O3 | A3 | A3 | O3 |
| JCT_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| JCT_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| JCT_L | deny allow deny allow | D3 | A3 | D3 | O3 |
| DSD_REL_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| DSD_REL_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| DSD_REL_L | deny allow deny allow | D3 | A3 | D3 | O3 |
| DSD_ABS_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| DSD_ABS_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| DSD_ABS_L | deny allow deny allow | D3 | A3 | D3 | O3 |
| FSL_REL_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| FSL_REL_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| FSL_ABS_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| FSL_ABS_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| MV_OUT | deny deny deny deny | I3 | I3 | I3 | I3 |
| HL_IN | deny deny deny deny | D3 | D3 | D3 | D3 |
| TRAV_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| TRAV_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| CASE_UP_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| CASE_UP_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| CASE_MIX_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| CASE_MIX_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| S83_R | deny allow deny allow | D3 | A3 | D3 | O3 |
| S83_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| ADS_R | deny allow deny allow | I3 | I3 | I3 | I3 |
| ADS_W | deny deny deny deny | D3 | D3 | D3 | D3 |
| GRANT_CASE_R | allow allow allow allow | O3 | A3 | O3 | O3 |

Totals: 222 denied as policy, 51 allowed as policy, 63 over-denial, 24 inconclusive, 0 policy violation. Probe names are explained in the script's docstring (`_R` read, `_W` write, `_L` list; JCT junction, DSD directory symlink, FSL file symlink, TRAV `..`, CASE spelling, S83 8.3 name, ADS stream; HL_IN a hard link into the grant). The sweep after the matrix found nothing unexpected in the ungranted folders (WSL view); the Windows-side sweep that `--cleanup-windows` runs is not part of these files.

## The 24 runs not judged

1. MV_OUT, 12 runs: the move out of the grant was never tested. The script of that commit started `mv` directly, and nono refused it before applying any sandbox: `nono: Command 'mv' is blocked: Command blocking is deprecated in v0.33.0 and only checks the directly-invoked startup command. Child processes can bypass it. Prefer filesystem, network, and command policies such as add_deny_access, narrower filesystem grants, unlink_protection, and network policy.` There was no "Applying sandbox" banner (exit 1), so the rows read INCONCLUSIVE, correctly. Since commit `448e237c` the probe starts `mv` through `sh -c` like the write probes, so Landlock judges the move; that has not been run. Until it is, a rename out of the grant is NOT covered by this record.
2. ADS_R, 12 runs: the control outside nono failed (`cat: '.../other/ads_host.txt:ads_stream': No such file or directory`) although Windows had created and read back the stream. On this setup a stream cannot be addressed by `name:stream` through 9P, so a denial inside nono would prove nothing. The probe stays to document that limit, and its expected verdict is INCONCLUSIVE; it is not a result about nono. ADS_W is a different case: its control succeeded (a write of a colon-named entry reads back under the same name), but whether that entry is an NTFS stream or a plain file under a mapped name was not checked from the Windows side. Its denial therefore shows only that a colon-named write into the ungranted folder is denied.

## Run 1 (pty) and why it is superseded

`runs/run1-pty-aborted-SUPERSEDED-20261014-230957.json`. Same script bytes, `--stdin-mode pty`, 23:10 local. Six runs of 360 happened. nono's working-directory prompt was answered N on all six, the sandboxed command ran and its write was denied, and then nono opened an interactive "Review denied paths" menu (keys: a grant-all, d deny-all, Space cycle, Enter confirm, Esc cancel; it listed `grant /mnt/c/wsl/p1755-run1 (write dirs)`) and waited for a key. The runner had no answer for it, so each run ran to the 60 s limit (60.07 to 60.18 s, exit 124). Two defects showed:

- The script read a timed-out run as DENIED_AS_POLICY, so the file's six rows say DENIED_AS_POLICY and its overall says NO_POLICY_VIOLATION_OBSERVED. Both are wrong. A run that did not finish proves neither a denial nor an allowance. The rows should read INCONCLUSIVE and the overall INCONCLUSIVE; they are kept as written so the wrong version stays visible.
- The abort after six consecutive timeouts stopped the matrix after 6 minutes. Without it the 360 runs would have taken about 6 hours at 60 s each.

Fixed in commit `dcd4b3f9`: a timed-out run reads INCONCLUSIVE (a violation already seen still wins), an aborted matrix reads INCONCLUSIVE overall, and the pty runner cancels the review menu with Esc (never a, d, Space or Enter) and records the denied-path lines nono printed (`nono_review_denied`). That fix has been tested against nono's real menu text from this run and against a simulated transcript, not against a live nono; no pty run of the fixed script exists yet.

## The 2026-10-12 record and why it is superseded

The first control (`agent-run-20261012-005615.json`, 4 cases by 4 probes by 3 runs, 18 denied, 12 allowed, 18 over-denial, 0 violation) is not copied here. It is superseded for two reasons. It stored only the first 500 characters of nono's stderr per row, and in 36 of its 48 rows that stops before the "Applying sandbox" line (12 of 48 carry it, all in case C). The script then accepted exit codes 0, 1 and 2 as proof that nono had started even without the banner. So the record cannot prove the banner for those 36 rows; that is a limit of the record, not evidence that the sandbox failed to start, and the record shows commands running under the sandbox (every case C row was allowed, B's in-grant list worked). Second, the machine moved: that record ran on kernel 6.18.40.1 and WSL 3.0.1, this one on 6.18.54.1 and 3.0.3.0. Its reading (no violation observed, the #2089 over-denial reproduces) agrees with run 2.

## Script changes made after these runs, and what they do to these verdicts

Run 2 used the script at `7da29183`; three later commits changed it. Applied to run 2's own 360 rows:

- `dcd4b3f9`, timeout rule (exit 124 reads INCONCLUSIVE): run 2 has no row with exit 124 (0 of 360), so the rule alters none of its verdicts. It does change run 1, whose six rows are the ones it exists for.
- `dcd4b3f9`, list probes judge by the name in the listing instead of exit code 0: the 48 list rows (L_IN, JCT_L, DSD_REL_L, DSD_ABS_L) keep their verdicts. The 33 exit-2 rows are plain permission errors without the name, and the 15 exit-0 rows carried the name under the old rule too. This is inferred, not read from the rows: piped rows do not store the command's stdout, only the stderr tail, so the 33 exit-2 rows end in `ls: cannot open directory ...: Permission denied` (ls could not open the directory and prints no entries), and the 15 exit-0 rows are allowed-by-policy probes that carried the name under the old rule too.
- `448e237c`, MV_OUT through `sh -c` and ADS_R marked as expected INCONCLUSIVE: changes how a later run produces the 12 MV_OUT rows and labels the 12 ADS_R rows, and alters none of run 2's verdicts.
- The pty Esc handling, the fixture-name gate and the "missing" environment facts do not touch run 2's verdicts.

## What this does not show

From the record's own list: virtiofs; truncate, delete, chmod, utime and extended attributes; links created from inside the sandbox, multi-hop links and links in nested folders; reparse points other than junction and symlink; 8.3 names of the granted path itself and case-sensitive-flagged folders; streams on folders; Windows-side changes while a run is in progress; other mounts, drives and UNC paths; other nono versions, other kernels and non-root users; network behaviour; more than 3 runs per case and probe on one machine. Also: a rename out of the grant (MV_OUT) and a stream read (ADS_R) were not judged; the pty path and the review menu were skipped in run 2; the Lead Architect's own run is owed; the load on the host was not controlled; the links were created by an elevated shell, so this tests how nono and 9P treat links already inside the grant, not who can plant them. Piped rows store only the stderr tail after the banner (400 characters in run 2), never the command's stdout, so the evidence for a violation (a listing or a file's content) would not appear on its row; the verdict rests on the effect checks the script runs in WSL after each run. Nothing here compares speed.

## Routing

No policy-denied operation succeeded, so nothing goes to nono's private advisory form. The public statement the data supports is narrow: in these cases the sandbox denied more than it should, never less. Any further post on #2089 rests on this folder, on the MV_OUT and pty gaps above being closed or named, and on the Lead Architect's own run.

## Files

- `runs/run2-piped-20261014-231822.json`: run 2, 360 rows, the record this README describes.
- `runs/run1-pty-aborted-SUPERSEDED-20261014-230957.json`: run 1, six rows, wrong verdicts kept visible.
- Both were passed through `scripts/scrub_public_identifiers.py`'s rewrite for the host name and the operator account name; neither name was present. One further field was redacted by hand (below), so the copies are NOT byte-identical to the files the run wrote.
- Redaction, 2026-10-15: `prepare_record.short_names.dir_x_base` and `dir_x_long_dir` held the raw `dir /x` output, whose header carries the drive's volume label and serial number, a stable machine identifier and not evidence. The header, the directory line and the free-space footer were removed from both fields; only the dated entry lines remain, and the script now records only those. Nothing else in either file changed.

| File | sha256 as run | sha256 as published |
|---|---|---|
| `runs/run1-pty-aborted-SUPERSEDED-20261014-230957.json` | `6f919f73b3b9fb224ccd6d91e69bf20282d4501cdadda283c51bdab45fdd042a` | `14e0503f58fbfe15c664ae6239cfdab417f2c4b85f153914f39912ce959831f3` |
| `runs/run2-piped-20261014-231822.json` | `6d27fe841cdcb308cea0eeddcb3825eb2c7c9bceb9cf80d8d30c7e2b24c79aa9` | `71abf7a3d75346fba990bd95f10a9a453d3d8d1b746a5250cd15b638ad1fdb7d` |
- Script and its self-test: `tools/probes/nono_9p_failclosed_control.py`; commits `7da29183` (the bytes that ran), `dcd4b3f9` and `448e237c` (fixes after these runs).
