# Disposition — independent adversarial review of the installer's batched git calls (#1699)

**Review:** independent adversarial-reviewer session (did not author the change), round 1 against
`0071e615`, round 2 against `ce79e417`. Round 1 blocked the merge on one finding and one missing lock.
**Author of the change and of this disposition:** this session.
**Outcome:** the batching is merged only after every verification in the installer has a test that fails
when the verification is removed; two review items are argued rather than changed, and two pre-existing
defects the review surfaced are ticketed with predicates.

```disposition
R1-1 when git died mid-stream on a corrupt object the refusal named the FIRST file instead of the bad one, because the parser blanked every entry on a non-zero exit | FIXED | ce79e417 - entries parsed intact before the failure keep their bytes; test_a_corrupt_object_is_named_not_the_first_file and test_entries_parsed_intact_before_git_died_keep_their_bytes
R1-2 _hashes raised UnicodeEncodeError for a path outside the console code page instead of the documented fail-closed empty answer | FIXED | ce79e417 - paths are sent as UTF-8 bytes on binary stdin and an unencodable path yields empty answers; test_a_path_outside_the_console_code_page_neither_crashes_nor_passes
R1-3 one unreadable installed file makes the drift review list every file as DRIFT, where the original listed one | REJECTED | argued: the batch is all-or-nothing on purpose (an answer count that differs from the request cannot be attributed to a file), the direction is fail-closed, and the reviewer could not construct a file git cannot open but Python can on Windows; if such a case is ever observed the per-file fallback is one line in _drift
R1-4 the lock file overclaimed and no test asserted the hash-verification refusals, so disabling the written-copy check passed all 271 git tests | FIXED | ce79e417 - tests for the written-copy refusal, the post-swap refusal, the drift report and the scripted wrong-count, failing-exit, short-body and other-object replies; a sweep of eight mutations of the new helpers and checks fails each one
R1-5 the cat-file reply was not checked against the object asked for | FIXED | ce79e417 - the reply must name the requested sha; test_a_reply_for_another_object_is_not_accepted
R1-6 the common-directory cache can go stale if the repository at a path is replaced inside one process | REJECTED | argued: the only in-process callers are the new test file, which clears it, and one harness that uses a single repository; the installer itself is one process per invocation. The docstring states the per-process lifetime
R2-1 dropping --no-filters from the batch call survived: nothing used a CRLF text file under core.autocrlf | FIXED | f97e4eee - test_hashes_are_of_the_raw_bytes_even_where_git_would_convert_line_endings asserts the precondition that the filtered hash differs
R2-2 encoding the stdin payload as the console code page survived the non-ASCII test because the accepted answer included empty | FIXED | f97e4eee - test_a_path_that_exists_only_in_utf8_not_in_the_console_code_page_gets_its_real_hash uses a character that is in cp1252 but not Latin-1
R2-3 the installer fails in a repository whose path has non-ASCII characters unless PYTHONUTF8 is set, in both the original and the batched installer | DEFERRED | #1704 blocked-by: #1704 closed - pre-existing on main 2cd59f8d and independent of this change; the ticket carries the reproduction and the fix shape
R2-4 --check reports the install record as not matching right after a successful install in a sha256-object-format repository, in both installers | DEFERRED | #1705 blocked-by: #1705 closed - pre-existing, no live impact (all repositories are sha1), ticket carries the scenario
```

## Measured effect (for the record; the gate figures are on #1699 and in `docs/performance/`)

One install on this machine: median 3.05 s before, 0.97 s after (n=8 per arm, interleaved, reviewer's
harness); git processes per install 76 before, 18 after by `GIT_TRACE` count (the commit message said
"about 12", which understated it). The installed files, git configuration, install record and log are
identical to the original installer's in every scenario the reviewer ran, including a cut swap and recovery.
