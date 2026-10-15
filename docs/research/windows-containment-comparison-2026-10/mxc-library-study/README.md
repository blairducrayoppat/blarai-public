# MXC library study (2026-10-11, #1740)

Three read-only studies of Microsoft MXC v1.0.0 (tag commit 7bf21024) as a library, with one skeptic check
per study. `studies.json` holds the three studies (backends; SDK and stateful lifecycle; audit mode and
maturity). `skeptic-checks.json` holds the three skeptic verdicts; all three were "holds_with_corrections".
The corrections are folded into the report section "MXC as a library". No container was run; only
`wxc-exec.exe --help` and `--probe` were executed. Source of the term "dynamic composition": Microsoft Build
2026 session BRK262 at 11:55 (transcript at C:/blarai-spike-1740-mxc/video-brk262/transcript.txt, not copied here).
Note: an earlier note cited c6f301d5 as the v1.0.0 commit; that is main's head on 2026-10-09, 20 commits ahead of the tag.
