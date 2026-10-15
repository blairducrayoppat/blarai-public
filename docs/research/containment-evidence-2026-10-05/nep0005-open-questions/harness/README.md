# halfset: guarded WFP harness

`halfset` installs, reads and removes Windows Filtering Platform (WFP) objects in exactly three test sublayers. It is one Rust file,
`halfset.rs`, built as a cargo example inside a copy of the pinned srt-win tree (anthropics/sandbox-runtime
`24eb39e94a6de386e83d126c52317d8e0fa49522`, `vendor/srt-win-src`). It uses only the `srt_win` library (`srt_win::wfp::install_filters`,
`uninstall_filters`, `filter_status`, `parse_guid`, `parse_port_range`, `srt_win::sid::*`) and the `windows` crate already in the lock.
`Cargo.toml` and `Cargo.lock` are never edited; `build-harness.ps1` proves both are byte-identical to the pinned copies before and after the build.

## Build

```
pwsh harness/build-harness.ps1            # shipped exe
pwsh harness/build-harness.ps1 -Toggle    # guard-toggle exe, used only by tests/refusals.ps1
```

The script copies the pinned tree to `C:/Users/_OPERATOR_/rust-bootstrap/halfset-build` (outside any git tree; it refuses a build dir inside one),
drops `halfset.rs` in as `examples/halfset.rs`, runs `cargo build --locked --example halfset`, and prints JSON with the sha256 of the exe,
of `halfset.rs` and of the pinned `Cargo.lock`. The lock hash and the `halfset.rs` hash are embedded in the exe at build time
(`HALFSET_PINNED_LOCK_SHA256`, `HALFSET_RS_SHA256`, read with `option_env!`) and shown by `halfset --version`. The script also writes
`build-record-shipped.json` / `build-record-toggle.json` into the build dir with the exe sha256 it produced; `tests/refusals.ps1` checks the
exe under test against that record and against the `halfset.rs` beside it.

## Subcommands

Each prints one JSON object on stdout.

| Command | Effect |
|---|---|
| `install --sublayer S --sid SID [--range LOW-HIGH] --live PROOF` | `install_filters` (default range 60080-60089), then read-back of the four filters |
| `status --sublayer S` | `filter_status`, verbatim under `srt_win_status` |
| `enum --sublayer S` | every filter at the two ALE connect layers in S: key, layer, name, kind, SID tag, port-range tag, user-condition flag, action, weight |
| `enum --all-ours` | every filter in S1/S2/S3 plus any filter at any layer whose name contains `srt-win` or `BlarAI #1763`, whose tag tool is `srt-win`, or that sits in a forbidden sublayer; exit 9 when any of those is outside S1/S2/S3 |
| `delete-filter --sublayer S --key GUID --live PROOF` | deletes one filter, only if that key is enumerated under S; reads back absent |
| `delete-sublayer --sublayer S --live PROOF` | refuses unless S holds no filter; deletes by key; reads back absent |
| `uninstall --sublayer S --live PROOF` | `uninstall_filters`, then `delete-sublayer` semantics |
| `selftest-refusals` | runs every guard check against fake environments and a fake filter source; opens no engine |
| `--version` | version, pinned SHA, pinned `Cargo.lock` sha256, `halfset.rs` sha256, `toggle_build` flag |

Exit codes: 0 ok, 1 selftest failed, 2 usage, 3 sublayer refused, 4 SID refused, 5 sublayer not empty, 6 not elevated and engine unreadable,
7 engine denied (code in the JSON), 8 read-back mismatch, 9 stop (a filter of ours or srt-win's outside S1/S2/S3), 10 engine error that is not a
denial, 11 delete target not under the named sublayer, 12 not armed, 13 trace file unusable (the engine was not touched).

Exit 6 is a read path (`enum`, `status`) denied while not elevated; exit 7 is any mutating path denied, or any denial while elevated. In both
the JSON carries `call`, `rc` (hex, verbatim from the engine) and `elevated`.

## Arming interlock

`install`, `delete-filter`, `delete-sublayer` and `uninstall` refuse with exit 12 before any engine open unless `--live <proof.json>` names a proof that
validates. The harness hashes its own exe (`current_exe` bytes, in-file SHA-256 pinned by the FIPS 180-4 vectors in `selftest-refusals`) and requires
the proof JSON to contain:

- `schema`: `"nep5-1763-proof-v1"`
- `halfset_exe_sha256`: equal to the running exe's sha256 (hex, case-insensitive)
- `halfset_rs_sha256`: equal to the `halfset.rs` sha256 embedded at build time
- `checks_failed`: the JSON integer `0`
- `written_utc`: an ISO 8601 timestamp with a zone designator (`2026-10-12T19:00:00Z` or an offset), not older than 24 hours and not more than 5 minutes in the future

A missing, unreadable, over-1-MiB, non-JSON or non-matching proof exits 12. `status` and `enum` need no token and reject `--live`. A rebuilt exe or an edited
`halfset.rs` makes every earlier proof invalid. The interlock runs after the pure argument, sublayer and SID guards, so those refusals (exit 2, 3, 4) are
unchanged, and before the first engine open.

The interlock gates intent, not authority. The proof's inputs are public (the exe's sha256, the hash `--version` prints, a clock), so anyone who can write a file anywhere can write a valid one; it exists so that a mutating run is a deliberate act and never an argument-encoding accident or a typo. `checks_failed: 0` is an unverified claim by whoever wrote the proof: the harness does not check that a self-test ran, so a proof is not evidence that one did.

## Guards

The sublayer, SID and arming guards are deny-by-default and run before the first engine call of the process. Guards 3 and 6 need the
engine: they run after a read-only enumeration opens it and before the first mutating call. Every error path denies.

1. **Sublayer allowlist (exit 3).** Only S1 `c971a69f-d6ab-4885-9b49-506d8aa51c86`, S2 `3e29ae7e-fd9f-413a-8b8d-da9bd3a96359`, S3 `6cf901ba-a6cd-4846-81a5-2598c55bdef5`. srt-win's default sublayer, the old arm 3 sublayer and anything else are refused, for every subcommand.
2. **SID allowlist for `install` (exit 4).** Exact string match against the two recorded test SIDs. blarai-spike's SID must also equal `LookupAccountName("blarai-spike")`; the stale SID must be unmapped (`Mapped`, `Unknown` and lookup errors refuse). The caller's own user SID, every group SID in the caller's token, well-known SIDs and anything else are refused. The caller token is read in full; if it cannot be read the install is refused.
3. **Empty sublayer for `install` (exit 5).** The sublayer is enumerated first; any filter in it refuses, because `install_filters` deletes every srt-win-tagged filter under the sublayer it is given.
4. **Elevation (exit 6 / 7).** Engine refusals are reported verbatim; the harness never crashes on them. The denial JSON carries `phase` and `write_attempted`. A denial in a precheck phase (`install_precheck`, `delete_filter_precheck`, `delete_sublayer_precheck`, `uninstall_precheck`) reports `write_attempted: false`: for a token that cannot enumerate, harness `install` and `delete-filter` cannot record a write verdict at all, because `install_filters` itself enumerates before its first add and the harness's own delete is preceded by an enumeration. Write verdicts for N1 (the account's own token) come only from the matrix's direct single add and single delete.
5. **Provenance.** The exe embeds its version, the pinned SHA, the pinned `Cargo.lock` sha256 and the `halfset.rs` sha256; `selftest-refusals` fails if either hash is missing. A trace file that cannot be written refuses with exit 13 (`trace_failed`) before the engine is touched.
6. **Stop sweep (exit 9).** `install`, `delete-filter`, `delete-sublayer` and `uninstall` first enumerate the ALE connect layers and stop, changing nothing, if a filter of ours or srt-win's exists outside S1/S2/S3. A sweep never cleans up.

`delete-sublayer` and `uninstall` check emptiness through the same function as `install` (guard 3), so the `nonempty` toggle and the fake-source rows cover all three. The engine's `FWP_E_IN_USE` is the second lock (exit 5) for a filter outside the ALE connect layers.
`enum --all-ours` rejects `--sublayer` (exit 2). `srt_win::wfp::parse_guid` strips braces independently, so `{S1`, `S1}` and S1 wrapped in two pairs of braces all parse to S1; the allowlist compares the parsed GUID and `selftest-refusals` pins the behaviour.

Residual: `install` prechecks the sublayer with one engine session and `install_filters` opens its own, so a concurrent elevated writer could slip a filter in between; srt-win's public API cannot close that window. The matrix runs with the fleet paused.

Every engine touch passes through `trace_engine_open`: it appends a line to the file named by `HALFSET_ENGINE_OPEN_TRACE` (when set) before the
engine is touched, and counts the touch in-process. `selftest-refusals` asserts the count is zero.

## Tests

`tests/refusals.ps1` (offline, no engine):

- Source binding: the `halfset.rs` beside the tests is hashed and both exes must report that hash in `--version`; each exe's sha256 must equal the build record.
- Part A, shipped exe: `--version` provenance; `selftest-refusals` (fake SID environments, a fake filter source, SHA-256 vectors, proof validation rows, brace forms, exit classification, embedded hashes, zero engine opens); wrong-sublayer refusals for all six subcommands (exit 3); `install` with the real caller user SID, every SID in the caller's real token, well-known SIDs and garbage (exit 4); each of the four mutating subcommands with a valid sublayer (and for `install` the recorded spike SID) and the token absent, pointing at a missing path, a non-JSON file, a proof naming a different exe hash and a proof with the wrong schema (exit 12); usage errors (exit 2). Refusal cases assert the engine-open trace file is empty or absent, except rows that run the shipped exe with a mutating subcommand: those point the trace variable at a directory so the exe exits 13 before any engine open whatever the guard under test does, and a bypass shows as 13 instead of the expected code. The tests never write a proof naming the real exe hash, so no row can arm a mutating subcommand.
- Part B, toggle checks: see below.

Guards 3 and 6 need an engine to run live, so their tests are the fake-source checks inside `selftest-refusals`.

### Toggle checks (each test fails if its guard is removed)

`build-harness.ps1 -Toggle` builds a second exe with `RUSTFLAGS="--cfg halfset_toggle"` (a compiler flag, so `Cargo.toml` stays untouched) into its own target dir.
In that build only, `HALFSET_TOGGLE_OFF=<guard>[,<guard>]` switches a guard off (`sublayer`, `sid`, `sid_lookup`, `nonempty`, `stop_sweep`, `interlock`), and every
engine entry point refuses without calling the engine, so the toggle exe cannot touch the engine either. The shipped exe contains no toggle code; `refusals.ps1`
scans its bytes for the variable name `HALFSET_TOGGLE_OFF` and asserts it is absent (with a control that finds it in the toggle exe).

With a guard off, `refusals.ps1` asserts that the same invocation is no longer refused with the expected exit code and that the trace file shows an engine entry was
reached (process-level, guards 1 and 2 and the interlock for all four mutating subcommands), and that the toggle exe's `selftest-refusals` exits 1 and names the check that caught the removal (guards 1, 2, the lookup part of 2, 3, 6, the interlock).
Without the variable the toggle exe refuses exactly as the shipped exe does, and its selftest passes.

## Not covered by any offline test

The engine-facing paths (enumeration, `install_filters`, deletes, read-backs, the non-elevated engine refusal code) run only against the real engine and are not exercised by
the tests above. The enumeration of `--all-ours` passes no template to `FwpmFilterCreateEnumHandle0` (all layers); the per-sublayer enumeration uses the same two-layer template as srt-win's own code.
