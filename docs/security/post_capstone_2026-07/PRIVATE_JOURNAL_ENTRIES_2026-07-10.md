# Private journal entries — unredacted originals (2026-07-10)

*Security-scoped. These are the UNREDACTED originals of two BUILD_JOURNAL.md
entries that were folded into the public journal in GENERICIZED form on
2026-07-11, per the Lead Architect decision recorded on Vikunja #799 c.1712:
security-posture facts about this box's live defenses are always genericized on
public surfaces (no security-product names, no which-rule-is-inert, no gap
mechanics, no re-visit-trigger specifics). The public journal carries the
governance narrative and the transferable lessons (LESSONS.md 234, 235, 240)
without the box-specific detail; this file preserves the full account for the
operator's own portfolio and operational record. Do NOT include this file in any
public export/sync.*

*Public counterparts (redacted), both dated 2026-07-10 in BUILD_JOURNAL.md:*
- *"The rule that was written into a plane nothing read" (enforcement-plane; lesson 240)*
- *"Building the door and the account that comes through it, both left locked" (lessons 234, 235)*

---

## Original 1 — the enforcement-plane finding (source fragment 2026-07-10_bitdefender-owns-the-firewall.md)

### 2026-07-10 — The firewall that wasn't there

*Plain summary: the ACP-01 per-SID egress block was proven INERT live — Bitdefender owns
filtering on this box, so Windows Firewall rules do not enforce; the LA decided to keep
Bitdefender and accept the egress gap; the containment floor shipped on its ACL + identity
legs with the gap consciously recorded (`-AcceptedEgressGap` verify mode, #775 c.1653).
Subsystem: ACP-01 containment / verify-coder-containment. Lesson class: verify-not-assume
(the §5.3 discipline), plus a new shape — the enforcement PLANE, not just the rule, is a
premise to verify.*

The Decision-1(b) design was careful about the rule: per-SID, never per-exe, the E8
precedent cited at every layer, the SDDL keyed to the coder account so the operator's own
tools could never be touched. Every review pass confirmed the rule was right. And the rule
was right. What nobody had verified was whether the thing the rule was written into was
actually in charge of the network.

The live proof said no. The coder-account probe connected to 1.1.1.1:443 with the block
rule enabled, direction outbound, action block, profile any — every attribute correct, no
enforcement. The check code was sound (it demanded a genuinely completed TCP connect, not
a faulted task read as success), so the reading had to be believed. The bisect that
settled it was one narrow, temporary rule: block 1.1.1.1 for ALL users, then connect as
the operator. The connect succeeded. At that point the per-SID condition was exonerated
and the enforcement plane was convicted: SecurityCenter2 named Bitdefender Firewall (with
a McAfee registration beside it, likely bloatware residue) as the registered provider.
Windows Firewall on this box is a rule store nothing reads.

The trade-off went to the LA with a recommendation: disable only Bitdefender's firewall
module so Defender Firewall — the only engine here that can express a per-ACCOUNT rule —
enforces the block; or keep Bitdefender and accept the gap, because Bitdefender's own
rules are per-application, which is exactly the E8 grain that broke the operator's tools
once already. The LA chose to keep Bitdefender and accept the gap. What made the
acceptance honest instead of silent: the verify script gained an explicit
`-AcceptedEgressGap` switch that turns check 1 into a WARN citing the decision and its
re-visit triggers (Bitdefender posture change, the VM leg going live, any egress
incident) — and WITHOUT the switch the check still fails hard, so the gap must be
consciously invoked on every run, never inherited. The four-check proof then went green
in real mode: secrets ACL-denied, loopback to the live model HTTP 200 as the coder, SID
verified on a real dispatch-spawned child, egress warned-and-accepted.

The day's other two provisioning lessons ride the same arc: the first supervised run
found the account couldn't run its own scheduled task (no batch-logon right) and couldn't
read the fleet's own code (the profile default-deny that protects the operator's secrets
also hides the scripts the coder must execute) — a "powerless" account still needs its
positive capabilities enumerated precisely, and only the live run finds the gap between
"denied everything" and "denied everything except exactly what the job requires."

**Proposed lesson:** a control written into an enforcement plane is a claim about the
PLANE, not just the rule — verify the plane enforces anything at all (a one-rule positive
control) before trusting any rule written into it; third-party security products silently
replace OS enforcement planes while the OS interfaces keep accepting writes.

**Next:** the fused-leg watched dispatch + the containment flip (next supervised session);
Bitdefender-module decision re-visits on its named triggers; McAfee-residue cleanup check.

---

## Original 2 — the containment substrate + driver (source fragment 2026-07-10_775-acp01-containment-driver.md)

### 2026-07-10 — Building the door and the account that comes through it, both left locked

*Plain summary: ACP-01 (#775) stages 2–4 built flag-dormant across two repos — the restricted `blarai-coder` containment substrate (agentic-setup), the ACP coder driver behind a `driver=stdin|acp` flag (blarai `acp_coder.py` + a fleet-lib shim), and the de-elevated coder-leg scheduled task — with both flags defaulting off so tonight's 23:00 battery runs the exact current path. Carries #779.*

The single insight that made ACP-01 one design instead of two is not mine — the design doc states it plainly: the ACP driver *holds opencode's JSON-RPC stdio*, so it must live on the same side of the privilege boundary as opencode. What building it taught me is where the seams actually fall once you honour that, and where the honest blockers are.

**Stage 3, the driver, and the version fault line.** The spike proved the ACP SDK needs Python 3.14; the BlarAI runtime `.venv` — and the whole standing gate — is 3.11. The spike's throwaway 3.14 venv is gone, so *running* the driver live now needs a fresh 3.14 venv plus a `pip install agent-client-protocol==0.11.0`, which lands squarely on the "installs into a runtime venv need coordinator sign-off" rule. That is the one thing I could not finish offline, and I did not paper over it — it is the first coordinator sign-off item in my report. But it shaped the architecture in a way I'd defend regardless: `acp_coder.py` imports `acp` *lazily*, inside the live-run function only. The pure logic — the §7.2 result contract, the step/spin cap rebuilt on typed events, the semantic idle bound, own-cancel tracking, the event→field map — is all module-top-level with no SDK dependency, so it is unit-tested under the 3.11 gate with a hand-built fake event stream (30 tests), *and* the timeout registry can import the module to read `ACP_IDLE_TIMEOUT_S` (120 s, registered with the spike's measured 83 s max-healthy-gap as its rationale). The lazy import isn't a workaround for the version gap — it *is* the flag-dormant guarantee at the Python layer: with `driver=stdin` the module is never imported, and even a mis-flip to `acp` with no interpreter falls back to stdin rather than crashing. The trade-off I accepted: the transcript the ACP path writes at `LogPath` is not yet byte-parity with the stdin JSON transcript that `Get-RunAnomalies` and the #762 plugin canary parse (I fold opencode's stderr so the load-lines survive, but the regex-consumers want step_finish markers). I chose to name that as a live-A/B verification item rather than fake a step_finish emitter now — the primary contract `Invoke-CandidateBuild` consumes is the result hashtable, and that is exact.

**The seam itself stayed surgical.** One new function, `Invoke-CoderDriver`, replaces the single `Invoke-AgentRun` call inside `Invoke-CandidateBuild`. With `driver=stdin` it delegates to `Invoke-AgentRun` with byte-identical arguments; the best-of-N selection, the gate, the merge are untouched. `Get-FleetDriverConfig` fails safe to the dormant defaults on any unreadable/absent/garbled manifest — a manifest we cannot read must never enable a non-default posture, which the fail-closed rule demands and a verify test drives (malformed JSON → stdin/off).

**Stage 2, containment, and the two things I deliberately did *not* build.** The design's cleverest move is to lean on the operator-profile default-deny instead of hand-punching Deny ACEs into `C:\Users\mrbla`. So provisioning adds *no* explicit Deny for the threat-model secret list — `~/.ssh`, `%LOCALAPPDATA%\BlarAI`, `~/.aws` — because a separate standard account is already denied all of it; explicit Deny is reserved for out-of-profile paths the operator names. The corollary breakage (the fleet's own worktrees live in-profile too) is fixed by relocating the throwaway base to `C:\blarai-fleet` with dual-SID Modify, gated behind the containment flag so `Resolve-WorktreeBase` returns today's `state\worktrees` path byte-identically until it flips — a lock I added to the existing verify suite. The firewall rule is per-SID, never per-exe: the E8 incident (a per-exe `curl`/`certutil` block broke the operator's own tools and was rightly reverted) is exactly the scar this avoids — one rule keyed to the coder SID covers the whole process tree and touches nothing the operator runs. The loopback-to-model exemption I did *not* assume: the block is deny-all-outbound and check 3 of the live proof is the positive control that observes `127.0.0.1:8000` still answers, with a documented `-ExcludeLoopbackFromBlock` fallback if the exemption ever fails to hold. And I did not run provisioning — author ≠ verifier on a security-critical machine change; every script is written ready for the coordinator's supervised run.

**Stage 4 and the elevation collision.** The battery self-elevates and the whole tree inherits that admin token, so running the coder as a *limited* account is fundamentally incompatible with "elevate the whole tree." The resolution the design names — run the *entire* coder leg as the restricted account via a scheduled task, talk to it over a file-queue — I built as `register-coder-leg-task.ps1` (RunLevel **Limited**, on-demand/no-trigger so it is dormant until Start-ScheduledTask fires it) plus `coder-leg-run.ps1` (claims one job, runs an ACP dispatch or a containment probe as the coder, writes the result). I weighed `runas /savecred` (rejected — caches a reusable credential in the very account we're isolating away from) against `CreateProcessWithLogonW` (most control, but I own the DPAPI plumbing) and took the scheduled-task path per D-C: the credential lands in the OS vault (LSA secrets), never on disk, and the account is deliberately *powerless* — a leaked coder credential buys an attacker nothing the ACLs and firewall don't already contain, which is the compensating control that makes vaulting acceptable. **#779 closes by construction here** — the typed `tool_call_update`/`agent_message_chunk` stream is a direct liveness signal that fires during a long single-artifact write, so the "slow single-file render reads as idle" blind spot the mtime/new-file heuristic had simply isn't in the model; I locked it as an explicit regression test (heartbeats on one in-flight edit keep the clock fresh across five simulated minutes). The ticket closes at merge+flip, not now.

Everything is flag-dormant: both flags at defaults, every touched code path behaves byte-identically to today, proven by the shipped-manifest-is-stdin/off verify, the byte-identity lock on `Resolve-WorktreeBase`, and 229 green in the touched-area gate subset.

**Follow-up — the live proof found two gaps the offline build could not (2026-07-10 evening).** The coordinator ran `provision-coder-account.ps1` and then the live proof, and it FAILED — which is exactly what a live proof is for, and exactly the "designed, not proven" trap the threat-model §5.3 names. Two findings, both the same shape: *the "lean on the profile default-deny" posture cuts both ways — it denies the coder the secrets AND the things it legitimately needs.* First, the coder-leg scheduled task registered fine (State `Ready`) but **never ran** — `LastTaskResult 0x41303`, `SCHED_S_TASK_HAS_NOT_RUN`. A password-principal task requires the "Log on as a batch job" right (`SeBatchLogonRight`), which a standard user does not hold by default; I had created a powerless account and then asked it to do something only a slightly-less-powerless account can. And the verify script experienced this as a *blind 180 s timeout* — it waited on a result from a task that never started, reporting a diagnosable condition as an opaque one. Second, even once it could run, it would have failed to **read its own code**: the fleet scripts, config, the `.venv314-acp`, and the blarai `shared/`+`tools/` driver modules are all profile-homed under `C:\Users\mrbla`, so the separate account was denied the very runner it was scheduled to execute. The fixes: grant `SeBatchLogonRight` in provisioning (secedit export→append→configure, preserving every existing holder, idempotent, mirrored in `-Rollback`); grant the coder Read+Execute on exactly the five code dirs and nothing more (never the repo roots, `certs`, or `%LOCALAPPDATA%\BlarAI`); and make the verify script poll the task's `LastRunTime`/`State` for ~20 s and fail loudly with the cause instead of waiting blind. The traverse-checking assumption those deep grants rely on (Everyone holds `SeChangeNotifyPrivilege`) I *verified on the box* rather than assuming — it holds — and the proof itself is the coder actually reading `coder-leg-run.ps1`. The lesson underneath: a "powerless" account still needs a precise, enumerated set of positive capabilities to do its one job, and only the live run finds the gap between "denied everything" and "denied everything except exactly what the task requires." The design doc's §3.4 breakage table now carries both classes.

**Proposed lesson:** *Keep a version-incompatible or heavy dependency out of a module's top-level imports when the module must also be flag-dormant and gate-tested.* Lazy-importing the 3.14-only ACP SDK inside the live-run function alone made the same file (a) inert under the default `stdin` flag, (b) unit-testable under the 3.11 standing gate with fakes, and (c) importable by the timeout registry — three properties one import placement bought. (Check for a recurrence of an existing dormancy/lazy-import lesson before minting; this may be a tally, not a new number.)

**Next:** the coordinator's supervised run — review the scripts, `provision-coder-account.ps1` (elevated) to create the account + per-SID rule + relocated tree + vaulted task, then `verify-coder-containment.ps1 -LoopbackStub` for the live proof (OVMS is down today; re-run without the stub in the GPU window for the real model path). Separately, the coordinator's GPU window runs the Stage 1 multi-turn A/B and, if it clears the D-A no-regression bar, provisions the 3.14 venv (the pip-install sign-off) and can flip `driver=acp` per run. `containment=restricted_account` flips only after all four containment checks are green. Neither flag flips tonight.
