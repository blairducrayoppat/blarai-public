# NEP-0005 open questions (#1763): build spec for the half-set matrix

Binding gate: docs/reviews/nep0005-open-questions-gate-v5-1763-2026-10-12.md, sha256 f1cfd80c188479c0a4478e9219d7a14633e9c7636208d23949b80c2dfe684502
(untracked, read it first). The Lead Architect granted new elevated live scripts and a locally built Rust harness on the real Windows Filtering
Platform (WFP) engine, test account and test sublayers only, and the Network Configuration Operators row (2026-10-12, #1763 comment 4074).
This spec is the build contract for the builders. Builders NEVER run anything that opens the real WFP engine for writing: only offline
self-tests (fake engine), compile, and refusal-path invocations that exit before any engine call. A builder reports; the author runs nothing
live until an independent reviewer has passed the code.

## Fixed constants (recorded; used by every script, never generated at run time)

| Name | Value |
|---|---|
| test account | `blarai-spike`, SID: the test account's SID, recorded in `harness/halfset.rs` |
| stale test SID (no such account) | `S-1-5-21-17630000-17630001-17630002-91763` (must NOT resolve via LookupAccountSid on this machine; the harness checks and refuses to use it if it does) |
| S1 srt-win harness sublayer | `c971a69f-d6ab-4885-9b49-506d8aa51c86` |
| S2 our own four-object-set sublayer | `3e29ae7e-fd9f-413a-8b8d-da9bd3a96359` |
| S3 different-sublayer case | `6cf901ba-a6cd-4846-81a5-2598c55bdef5` |
| srt-win default sublayer (REFUSED everywhere) | `2c5d0ad6-5f3b-4d4e-9b8f-1a3e7c9d0b21` |
| old arm 3 sublayer / provider (not reused) | `7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02` / `...3f01` |
| our provider for S2/S3 objects | NEW fixed GUID `3e29ae7e-fd9f-413a-8b8d-da9bd3a96360`, name `BlarAI #1763 provider` |
| our marker in every display name | `BlarAI #1763` |
| srt-win filter display names | `srt-win-v4-block-user` style (read the source) |
| pinned srt-win source | anthropics/sandbox-runtime `24eb39e94a6de386e83d126c52317d8e0fa49522`, dir `vendor/srt-win-src`, extracted at `C:/Users/_OPERATOR_/rust-bootstrap/srt-src-24eb39e9` (built OK: `cargo build --locked --lib`) |

The three sublayers are the ONLY sublayers any script may add to or delete. Any enumeration that finds a filter of ours or srt-win's under any other
sublayer is a stop (exit code per script contract), never a cleanup.

## Part 1: Rust harness `halfset` (builder B1)

One file `harness/halfset.rs`, built as a cargo EXAMPLE inside a copy of the pinned srt-win tree so Cargo.toml and Cargo.lock stay byte-identical
(`cargo build --locked --example halfset`); the build script `harness/build-harness.ps1` copies the pinned tree to a build dir, drops the example in,
builds, and prints the sha256 of the exe, of halfset.rs, and of the pinned Cargo.lock. Uses only the `srt_win` library (public `srt_win::wfp::*`) plus the
`windows` crate already in the lock (for our own enumeration, single-filter delete and sublayer delete: `for_each_tagged_filter` and `delete_tagged_filters`
are private, so the example enumerates with FwpmFilterCreateEnumHandle0 / FwpmFilterEnum0 itself, ALE_AUTH_CONNECT_V4 and V6, and deletes with
FwpmFilterDeleteByKey0 and FwpmSubLayerDeleteByKey0).

Subcommands (all print ONE JSON object on stdout; exit codes below):

* `install --sublayer S --sid SID [--range LOW-HIGH]` calls `srt_win::wfp::install_filters` (default range 60080-60089).
* `status --sublayer S` calls `srt_win::wfp::filter_status`; prints its JSON verbatim inside `{"srt_win_status": ...}`.
* `enum --sublayer S` enumerates ALL filters at the two ALE connect layers whose sublayerKey == S (tagged or not), printing key, layer, display name,
  kind (from the providerData tag when present), user SID tag, port range tag, and whether the filter carries a user condition. Also `--all-ours`: every
  filter in the three test sublayers plus any filter anywhere whose name contains `srt-win` or `BlarAI #1763` (the stop-condition sweep).
* `delete-filter --sublayer S --key GUID` deletes ONE filter by key, only if that key is currently enumerated under S, and then reads back absent.
* `delete-sublayer --sublayer S` refuses unless S has zero filters; deletes by key; reads back absent.
* `uninstall --sublayer S` calls `srt_win::wfp::uninstall_filters` then `delete-sublayer` semantics (srt-win's uninstall does not delete the sublayer).
* `selftest-refusals` prints each refusal check result (below) without opening the engine.

Guards, ALL evaluated before any engine call (the first `FwpmEngineOpen0` in the process happens after them), each with an offline test:

1. Sublayer allowlist: only S1, S2, S3. Refuse srt-win's default GUID, the old arm 3 sublayer, anything else (exit 3).
2. `install` SID allowlist: only blarai-spike's SID (and it must equal LookupAccountName("blarai-spike")) or the stale test SID (and it must NOT resolve).
   The operator's own SID, every group SID in the caller's token, every well-known SID, and anything else is refused (exit 4). The test feeds the real
   operator SID (WindowsIdentity.GetCurrent equivalent via the harness's own token read) and a token-group SID and checks exit 4 and that no engine open
   happened (an env var `HALFSET_ENGINE_OPEN_TRACE` file the harness appends to on engine open; the test asserts it is empty/absent).
3. `install` refuses a sublayer that already holds ANY filter (enumerate first; exit 5), because `install_filters` deletes every srt-win-tagged
   filter under the sublayer it is given.
4. Not elevated -> exit 6 with the access-denied code recorded (this is also how N1 records the non-elevated add: see Part 2 row N1; the harness must be
   runnable non-elevated for `enum`/`status`/`install` and report the engine's refusal code verbatim, exit 7 `engine_denied`, never crash).
5. Build embeds its own version string, the pinned SHA and the sha256 of the pinned Cargo.lock; `--version` prints them.

Exit codes: 0 ok, 3 sublayer refused, 4 SID refused, 5 sublayer not empty, 6 not elevated and engine unreadable, 7 engine denied (code in JSON),
8 read-back mismatch, 9 stop (a filter of ours/srt-win outside S1/S2/S3), 2 usage.

Also in `harness/`: `README.md` (what it is, how built, the guards) and `tests/refusals.ps1` (runs the refusal checks; offline; no engine).

## Part 2: PowerShell matrix (builder B2)

Directory `scripts/` beside this SPEC (new files only; do not edit the arm 1-3 scripts, which are hash-bound into the existing rollback proof. Reuse
their libraries by dot-sourcing through the SAME `Get-VerifiedLibBlock` pattern from `arm3-persist/scripts/spike-persist-lib.ps1`; read that library,
`spike-task-driver.ps1`, `spike-wfp-persist.ps1`, `Start-ElevatedOnce.ps1`, `spike-lib.ps1` and `arm3-persist/DESIGN.md` first). New live-folder files go to
`C:/ProgramData/BlarAI/trackb-live` via the existing `Convert-ToLive.ps1` pattern. The proof gate pattern is mandatory: no add path is reachable until
`-SelfTest -WriteProof` has passed for the NEW code set (a new proof file `rollback-selftest-proof-1763.json`, binding the sha256 of every new script, the
harness exe and halfset.rs, plus the pinned Cargo.lock hash, plus the existing library hashes it loads). Rollback is by KEY, self-tested first, with a
self-contained manual rollback snippet printed by `-DryRun` (delete the filters by enumeration of S1/S2/S3, then the three sublayers, then the provider).

Matrix runner `spike-nep5-matrix.ps1` modes: `-SelfTest [-WriteProof]`, `-DryRun`, `-Check` (read-only sweep of S1/S2/S3 and the marker/name export; exit 20 only when
everything reads absent, 21 something present, 22 unreadable), `-Remove` (sweep and delete by key everything in S1/S2/S3 and our provider, then verify with the
direct removal checks), `-Run -Phase <halfset|n1|...>`. Every state follows the same cycle, THREE passes each, with the order fixed:

1. direct sweep: S1, S2, S3 enumerate zero, sublayers absent, name/GUID export has 0 hits (refuse to add on anything else);
2. control: the account connects (v4 and v6 loopback listeners outside any permit range, plus one inside 60080-60089) BEFORE any filter, and the operator connects
   (operator watchdog as in arm 3a: two failed operator connects in a row -> remove by key and stop, exit 9);
3. add the state (harness `install` for srt-win states then `delete-filter` for the half-states; our own adder for our states);
4. record `srt-win status` (harness `status`) and `-Check`-style reading of our four keys, `enum` of the sublayer;
5. the account's connects through the gate (blocked = Windows error 10013), on 127.0.0.1 and [::1], listener outside the permit range (verify's shape) and
   inside the range; operator connects during;
6. remove by key, read back with the direct checks of step 1, record, and refuse to continue to the next state if anything reads back present.

States (srt-win rows S1; every row records status, enum, account v4/v6 out-of-range, account v4/v6 in-range, operator):
 R0 no filters (control); R1 full set from `install_filters`; R2 V4 block deleted (V6 block + permits remain); R3 V6 block deleted (V4 block + permits remain);
 R4 both blocks deleted, permits remain; R5 permits deleted, blocks remain; R6 stale: full set for the stale test SID (account unblocked, status installed);
 R7 S3 case: our own unlabelled block filter for the account in S3 while srt-win's status is read on S1 (empty): status absent while the account is blocked.
Our rows S2 (our four-object set with provider, using the `BlarAI #1763` names; new adder, proof-gated): V4 only, V6 only, permit without block, exact-port
 permit (admin adds a permit for 127.0.0.1:<one port> without a user condition, then the account connects to that exact port and a neighbour), a block with no
 provider attempted (record the engine's refusal as the result), a filter naming a missing sublayer attempted (record the refusal). The exact-port permit
 and refusals are recorded; the S3 and refusal rows stay in the evidence bundle, out of any comment draft.
N1 (non-elevated add): the account's own standard token (blarai-spike, via the existing task driver; NOT the operator's token, NOT the elevated session) runs the
 our own direct single add against S2 (one `FwpmFilterAdd0`, no preceding enumeration) and a direct single `FwpmFilterDeleteByKey0` against a test filter; the expected result is `engine_denied` with the status code
 recorded verbatim. Harness `install` and `delete-filter` cannot record a write verdict for a token that is denied enumeration (they stop at the precheck with `write_attempted: false`, and `install` also refuses the caller's own SID), so N1's add and delete verdicts come only from the direct single add and delete. If either succeeds, record it, remove, and exit 9 (a finding and a stop).

Outputs to an admin-only out dir (same guard as arm 3b: refuse junction/symlink/hard-linked targets): `nep5-results.json` (one record per state per pass:
timestamps, clock, exact commands, statuses, exit codes, the engine status codes), the per-pass sweep records and the exports. Sanitisation for the public
bundle is a later step: do not strip anything at source.

Probe mechanics: reuse the arm 2/3 account task (`spike-run-test.ps1` probe mode copied by `spike-task-driver.ps1`); extend by a NEW probe script (new file;
the existing one is hash-bound) that, as blarai-spike, attempts a TCP connect to a given `127.0.0.1:port` or `[::1]:port` and prints `{"family","port","result"}`
with the Win32 error code. Listeners are started by the operator side (elevated task), bound outside any permit range and one inside 60080-60089, on both
families; verify the [::1] listener actually binds before trusting a result (if IPv6 loopback cannot bind, the row is NOT RUN, never "blocked").

## Part 3: Network Configuration Operators row (builder B3, after B1/B2 review; its own script `spike-nep5-nco.ps1`)

Creates a throwaway local account `blarai-nco-1763` (random password held only in memory/DPAPI-free: never written to disk; not in any other group; deny
interactive logon not required: it logs on through `CreateProcessWithLogonW`/the task driver pattern the arms already use, read how `spike-provision.ps1`
does it and reuse it), adds it to the local group `Network Configuration Operators` (well-known SID S-1-5-32-556), then from that account's NON-elevated token
tries: add an exact-port permit filter in S2 (needs the S2 sublayer to exist: created by us elevated first, with a recorded security descriptor), delete one
of our own test block filters in S2, and add under S3. It records the engine's status codes. Also records the live engine access list (FwpmEngineGetSecurityInfo0
dump as SDDL) before and after. Then removes the account and the group membership and verifies both gone by direct reads (Get-LocalGroupMember on the group
and `net user`), plus the S1/S2/S3 sweep. Same proof gate, same stop conditions; the account name is a recorded constant, and the script refuses to touch any
group other than S-1-5-32-556 and any account other than `blarai-nco-1763`. If the group membership cannot be removed and verified, exit 9 with the manual rollback
printed (`net localgroup "Network Configuration Operators" blarai-nco-1763 /delete`, `net user blarai-nco-1763 /delete`).

## Review and run order

B1 and B2 build in parallel (disjoint files) -> independent adversarial review of each (a Fable reviewer, reads the code, runs offline tests, attacks the guards,
never writes the fix) -> author fixes -> re-review -> `-SelfTest -WriteProof` -> `-DryRun` -> live phases in order: R0..R7 and our S2 rows (3 passes), N1, then B3
after its own review. Each live run through `Start-ElevatedOnce.ps1` from the admin-only live folder; the Lead Architect's session is elevated so no UAC prompt.
