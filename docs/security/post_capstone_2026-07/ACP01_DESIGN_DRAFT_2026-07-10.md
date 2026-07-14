# ACP-01 — Design Draft: the opencode ACP driver seam + Decision-1(b) containment

**Ticket:** #775 (ACP-01) · carries #779 · **Status:** DRAFT — build-ready (uncommitted, no code/config touched) · **Date:** 2026-07-10
**Builds on:** the #759 ACP spike (verdict GO, `state/acp-spike/RESULTS.md`) and the #787 Phase-1 dispatch threat model (`PHASE1_DISPATCH_THREAT_MODEL.md`, §5 = the Decision-1(b) containment frame).
**Scope of this doc:** DESIGN + BUILD SPEC. It does not itself build, provision an account, or write a firewall rule — but it is written so a builder executes from it directly (the LA design-review gate was removed 2026-07-10; the coordinator reviews, then the build dispatches). §7 carries the concrete anchors + definition-of-done. Where a genuine call is open (§6), the build proceeds on the stated **default** unless the reviewer overrides — no decision blocks the build.

---

## 0. Recommendation up front

Build ACP-01 in four flag-dormant stages, **A/B-first, containment-in**: (1) run the one multi-turn GPU A/B the spike could not isolate; (2) in parallel, provision the restricted coder account + per-SID firewall and prove it live; (3) build the ACP driver behind a `driver=stdin|acp` flag; (4) fuse them by running the *entire* coder leg (ACP driver **and** opencode) as the restricted account, launched from the elevated orchestrator via a scheduled task and talked to over a file-queue — never over opencode's stdio. Default stays `stdin` + operator-account until both the A/B says GO and a live containment proof is green, so nothing merged can break tonight's 23:00 battery. The single load-bearing design insight: **the ACP driver holds opencode's JSON-RPC stdio, so it must live on the same side of the privilege boundary as opencode** — that is what makes the de-elevation and the ACP seam one design, not two.

The big decisions are already made (ACP go is A/B-gated per #759; containment is 1(b); hybrid-VM is the direction; Windows-guest dropped). The genuinely open calls are three, in §6.

---

## 1. The A/B — what "ACP beats the current driver" means, measurably

The #759 spike already settled most of this against our real config; ACP-01 does not re-derive it, it finishes the one measurement the spike flagged as unfinished.

**Already proven by the spike (transport-attributable, cite — do not re-run):**

| Axis | stdin driver (today) | ACP driver | Verdict |
|---|---|---|---|
| Turn visibility | 7 regex hit-counts over a JSON blob | **212 typed events** — `tool_call` lifecycle (pending→in_progress→completed/**failed**), per-call IDs, `usage_update` | ACP decisively richer |
| Failure visibility | a failed edit is just *absent* | 4 failed tool calls surfaced explicitly | ACP |
| Cancellation | tree-kill only | cooperative `session/cancel` **~2.1 s, clean, zero orphans** (×2 probes) | ACP |
| Stall signal | indirect mtime + CPU probe, `IdleTimeoutSec=240 s` (CPU probe false-doomed a healthy GPU phase, #687) | direct "no `session/update` for ~120 s" — cannot confuse *thinking* with *wedged* | ACP |
| Config/plugin parity | baseline | SHA256-identical config, both plugins load, 0 loader errors in ACP mode | parity holds |

**The one axis still open — and the only new GPU work the A/B needs:** wall-clock / token-cost. The spike's single-turn wall-clock was **confounded** by the build agent's temperature-0.7 non-determinism (the ACP leg stochastically fell into a coder debug loop; baseline happened to converge), so it is *not* a transport measurement. The real ACP win — a **persistent session amortizing the per-turn opencode re-spawn across the fleet's multi-turn review-fix laps** — was never isolated because a single-turn task cannot show it. That is the measurement ACP-01 runs.

**Cheap NO-GPU parity probes to run FIRST (lesson 225 — gate the GPU on the cheap check):** these are the spike's recon protocol, re-run as a pre-flight so a config/plugin drift never wastes the GPU window. (a) `opencode acp` handshake → `protocolVersion:1`, agentInfo. (b) Config parity: the loaded `~/.config/opencode/opencode.json` SHA256 == the coder-side config we intend to use. (c) **Plugin parity: both fleet plugins print their load-lines with 0 loader errors** — this is why the A/B must run *after* #764's plugin-loader fix deploys; a pre-fix baseline is not comparison-grade. (d) `set_config_option` flips the model to `local/coder-30b` and pins `local/*` (never opencode's cloud `opencode/*-free` models — egress hygiene). All CPU-only, no provider calls.

**The single GPU-window A/B protocol:** one real, representative fleet task (a genuine multi-lap build → verify-fail → review-fix task, not a one-shot `rpn.py`), run through **both** drivers, **same model, same seed of config, plugins active**, in a machine-free window (no battery, no live dispatch). Metrics per leg: total wall-clock, total tokens (ACP `usage_update` vs baseline transcript accounting), turns-to-green, and — the amortization signal — **per-lap opencode process starts** (stdin re-spawns once per lap; ACP holds one session). Because the coder is stochastic at temp 0.7, run the pair 2–3 times and report the distribution, naming the confound rather than hiding it (the spike's discipline). **Success bar → decision D-A in §6.**

---

## 2. The seam — where the ACP driver plugs in, behind a flag

**Where it plugs in.** The stdin driver is `Invoke-AgentRun` in `fleet-lib.ps1` — it spawns `opencode.exe run …` (`:386-407`), monitors by regexing the JSON transcript, and tree-kills on timeout. Every candidate build routes through `Invoke-CandidateBuild` (the `$BuildTestVerify` adapter at `new-agent-task.ps1:263-271`). The spike is explicit that the production ACP client belongs on the **Python** side beside `tools/dispatch_harness/monitor.py` (where monitoring already lives), not in PowerShell — the JSON-RPC event loop, the SDK (`agent-client-protocol` 0.11.0), and the tree-kill all want to be Python.

So the seam is a **driver abstraction** the PowerShell candidate loop calls: today it calls `Invoke-AgentRun` (spawn + regex-monitor); with the flag on, the same call delegates to the Python ACP client, which drives a persistent `opencode acp` session and returns the *same* result contract (`TimedOut/Capped/ExitCode/LogPath/Seconds` — the shape `Invoke-CandidateBuild` already consumes). The best-of-N selection, the deterministic gate, the merge (`Test-ShouldMerge`, `new-agent-task.ps1:508-519`) are **unchanged** — ACP replaces only *how the coder is driven and watched*, never *how the winner is chosen*.

**Coexistence + flag.** A `[fleet_dispatch].driver = "stdin" | "acp"` knob (default `stdin`). Both drivers stay in the tree; the flag selects per run — the spike's mandated posture is "a parallel driver you can switch per run, never a rip-and-replace."

**Fallback + rollback.** (a) *Config fallback:* if the ACP client fails to hand-shake or the SDK import fails, the driver logs and falls back to `stdin` for that run (fail-*open to the working driver*, since this is a dev-tooling reliability choice, not a security boundary — the security boundary is §3, independent of which driver drove). (b) *Rollback:* flip the flag to `stdin`; the ACP code is inert. (c) The ACP client must reuse the proven **`terminate_process_tree`** — the spike found the SDK's connection-close orphans opencode's node tree (9 children reaped), so tree-kill is a build requirement, not optional. It must also **rebuild the step/spin cap on the event stream** (ACP has no native `MaxSteps`; the typed events make this *easier* than the regex version), and **track its own cancels** (opencode returns `StopReason=end_turn` on a cancel, not `cancelled` — a real fidelity gap; don't trust it).

**#779 closes here, by construction.** The idle-breaker blind spot (a slow single-file render reads as idle because no *new-file* events fire) is exactly the inference class the typed stream retires: `tool_call_update` + `agent_message_chunk` are a direct liveness signal that fires during a long single-artifact write. ACP-01 fixes #779 in the event model rather than patching the mtime/size heuristic a second time — as the #779 ticket itself recommends.

**Bonus, named honestly:** ACP's `session/request_permission` (`allow_once` / `allow_always` / `reject_once`) lets the driver **programmatically mediate individual tool calls before they run** — a native protocol version of today's static `opencode.json` ask/deny policy (e.g. auto-reject a bash `tool_call` whose command matches an egress verb). This is worth wiring as defense-in-depth, **but it sits at opencode's tool layer (B4/B5) and a build child bypasses it** — so it is a supplement to, never a substitute for, the §3 OS floor.

---

## 3. Containment integration — building the (b) floor into the seam

Decision-1(b) is the floor: a restricted Windows account + a per-SID deny-by-default outbound firewall rule, for *every* dispatched job. ACP-01 is where it gets built because ACP-01 rebuilds the exact spawn seam.

### 3.1 The coder account

- **Identity:** a local **standard** account, `blarai-coder` (working name), member of **Users only** — explicitly *not* Administrators / Power Users. Standard-user integrity is the point of the de-elevation (§3.3).
- **What it must not read** (the threat-model §3 secret list): `~/.ssh/id_*`, `~/.git-credentials`, `%LOCALAPPDATA%\BlarAI` (keystores, `sessions.db`, `substrate.db`), the backup/secrets-staging folder, `~/.aws` / `~/.azure` / `~/.config/gcloud`.
- **How the ACLs get scoped — lean on the profile boundary, don't hand-punch grants into it.** Almost every secret above lives *under the operator's profile* `C:\Users\mrbla`, which Windows already **default-denies** to any other standard user. So the bulk of the containment is free the moment the coder is a separate account. Explicit `Deny` ACEs are then added only for secret paths that live *outside* the operator profile (or where inheritance was ever loosened) — belt over the default suspenders.
- **The corollary "what breaks":** the fleet's working dirs *also* live under the operator profile — the worktree base (`agentic-setup/state/worktrees`) and the target repos (`C:/Users/mrbla/projects`). A separate standard account is default-denied *those too*. **Mitigation:** relocate the throwaway worktree base out of the operator profile to a shared tree both SIDs can modify (e.g. `C:\blarai-fleet\worktrees`), so the profile default-deny stays intact and we don't poke read-holes into `C:\Users\mrbla`; grant the coder SID **modify** on `projects` explicitly (scoped, and paired with the §5.2 footgun — never point the fleet at a repo holding live secrets). This on-disk relocation is decision **D-B** in §6.

### 3.2 The per-SID outbound firewall rule

- **Mechanism:** Windows Defender Firewall supports user-scoped rules via the Windows Filtering Platform's `ALE_USER_ID` condition, exposed as `New-NetFirewallRule -Direction Outbound -Action Block -LocalUser <SDDL-of-coder-SID> -Profile Any`. The rule fires **only when the connecting process's token is the coder SID**, and an explicit block outranks any existing allow.
- **Why per-SID, not per-exe (the E8 precedent):** a per-exe/global block on `curl`/`certutil` (a) cannot enumerate every egress-capable binary a build spawns — `python`, `node`, `git`, `uv`, `pip`, `dotnet`, `nuget`, `powershell`, `msbuild` — and (b) broke the operator's *own* use of those same binaries and was rightly reverted (STATUS.md E8). A per-SID block covers the whole coder process tree regardless of binary, and touches **only** the coder account — the operator's identical tools are untouched. This is the structural fix the threat model's §5.1 calls for.
- **The loopback caveat (why the live proof needs a fifth check):** opencode reaches the model over **loopback** (`127.0.0.1:8000`/`:8099`). An outbound block that is even slightly too broad — or a WFP loopback assumption that doesn't hold here — would kill the coder's model access and silently no-op *every* dispatch. Windows normally exempts `127.0.0.0/8` from connect-filtering, but per the project's own verify-not-assume doctrine this must be **observed**, not assumed → §4 adds a loopback positive-control.

### 3.3 The de-elevated coder leg — the elevation collision, resolved

The overnight battery self-elevates to Administrator (`run-battery-night.ps1:63-82`) and the whole dispatch tree inherits that token, so the coder runs *elevated* today. A restricted coder account is fundamentally incompatible with "elevate the whole tree." ACP-01 must launch the coder leg as the restricted account **even from an elevated orchestrator**. Three mechanisms:

| Mechanism | How | Trade-off |
|---|---|---|
| `runas /savecred` | caches the coder password in the *operator's* Credential Manager, replayed on each launch | **Reject** — stores a reusable credential *in the very account we're isolating away from*; a coder-side compromise (or any operator-context process) can replay it. Defeats the boundary. |
| `CreateProcessWithLogonW` | Win32 API; supply coder user+password, it does the logon, you get full token/env/handle control | Most control (custom environment block, and it can **inherit the stdio pipes the ACP driver needs**). Cost: you own the credential handling (a DPAPI/LSA-protected secret) and the P/Invoke plumbing. |
| **Scheduled-task-as-coder** | pre-register a task set to run as `blarai-coder`; the elevated orchestrator triggers it (`Start-ScheduledTask`); per-dispatch inputs ride a file-queue | Credential lives in the **OS credential vault (LSA secrets)**, not the operator's reusable profile — beats `/savecred`. De-elevates **structurally** regardless of the trigger's integrity. Reuses the fleet's existing patterns (the battery *already* runs this way; dispatches already read queue files + poll result files). Cost: no direct stdio/argv — indirect by design. |

**Recommendation: scheduled-task-as-coder for v1**, with `CreateProcessWithLogonW` as the named direction if real-time control proves necessary. Rationale: the credential is OS-vaulted not operator-reusable; it de-elevates structurally; and it reuses proven machinery (battery precedent). Trade-off named: less real-time control (inputs and results go through files, which the fleet already does).

**But — the stdio collision, and how it resolves the whole design.** A scheduled task does *not* hand the orchestrator opencode's stdin/stdout, and the ACP driver *is* a JSON-RPC conversation over exactly those pipes. So you cannot "launch opencode as a task and drive it over ACP from the orchestrator." The resolution: **run the entire coder leg — the Python ACP driver *and* the opencode process it spawns — as the restricted account.** The scheduled task launches the *ACP driver* as `blarai-coder`; the driver spawns `opencode acp` as its own same-SID child and holds the stdio pipes *within* the coder-account process tree; the elevated orchestrator communicates with the driver over a **file-queue** (task inputs) + **result files** (transcripts/scorecards it already polls). One coder-SID process tree — driver, opencode, node children, build children — all covered by the one firewall SID-block and the ACL-deny, and the elevated orchestrator never touches opencode's stdio. (If v2 wants `CreateProcessWithLogonW` for tighter control, the same "whole leg as coder" shape holds — the driver is still the same-SID parent of opencode.)

### 3.4 What else breaks under a separate account, and the mitigation

| Breakage | Why | Mitigation |
|---|---|---|
| **opencode config not found** | opencode reads `~/.config/opencode/{opencode.json,AGENTS.md,plugin/}` — under the *operator* profile; the coder's `~` is `C:\Users\blarai-coder` | Point the coder's opencode config at the repo SSOT `configs/opencode.json` via env, **and** use the spike-proven **per-worktree `.opencode/plugin/` injection** (project-level plugins load in ACP mode). This also hardens the #764-class "global plugins silently dead" fragility by making plugin loading worktree-local + canary-verifiable. |
| **worktree file ownership at merge** | coder-created files are owned by `blarai-coder`; the operator/orchestrator later merges → git "dubious ownership" + ACL friction | Shared working tree where **both** SIDs have modify (inherited ACEs); operator adds the base to git `safe.directory`; merge stays orchestrator-side (it writes the operator's real `main`). |
| **git config absent** | the coder profile has an empty `.gitconfig` — no identity, no `safe.directory`, no autocrlf | The fleet already sets `-c user.email=agent@local -c user.name=coding-agent` on its commits; pre-seed a minimal coder `.gitconfig` (identity + `safe.directory` + autocrlf). Keep credential helpers **out** (the coder must not push, and can't reach the net anyway). |
| **cold npm/uv/pip caches** | package caches are per-profile; the coder starts cold, and with **egress blocked** a cold cache that needs a fetch **fails** | This is the dependency-mirror follow-up (§5) — a pre-staged local mirror the coder reaches over loopback/granted-path. **Named, not solved here.** |
| **the fleet's own code is profile-homed** *(found live 2026-07-10)* | the fleet scripts/config/venv (`agentic-setup\{scripts,configs,.venv314-acp}`) and the driver modules (`blarai\{shared,tools}`) all live UNDER `C:\Users\mrbla`, default-denied to a separate standard account — so the coder could not even **read** its own runner `coder-leg-run.ps1` (icacls showed SYSTEM/Administrators/mrbla only, no coder ACE). The "lean on the profile default-deny" posture (§3.1) cuts BOTH ways: it denies the coder the secrets *and* the code. | Grant the coder **Read+Execute** on EXACTLY those 5 code dirs (`provision-coder-account.ps1` step 7, SSOT in `coder-provisioning-lib.ps1`), and **nothing more** — never the repo roots wholesale, never `blarai\certs`, never `%LOCALAPPDATA%\BlarAI`. Deep grants work without a grant on the profile root because **Everyone holds Bypass Traverse Checking** (`SeChangeNotifyPrivilege` includes `S-1-1-0` — verified on this box) — *proven, not assumed*, by `verify-coder-containment.ps1` actually reading the runner. |
| **the account can't run its scheduled task** *(found live 2026-07-10)* | a password-principal scheduled task REQUIRES the **"Log on as a batch job"** right (`SeBatchLogonRight`), which a standard user does NOT hold by default — so `\BlarAI\BlarAI-Coder-Leg` registered fine (State `Ready`) but **never ran**: `LastTaskResult 0x41303` (`SCHED_S_TASK_HAS_NOT_RUN`), and the verify script waited 180 s blind on a task that never started. | Grant `SeBatchLogonRight` to the coder SID in provisioning (`provision-coder-account.ps1` step 1, via `secedit` export→append→configure, **preserving all existing holders**; idempotent; mirrored in `-Rollback`). And make `verify-coder-containment.ps1` **detect the non-start** (poll the task's `LastRunTime`/`State` for ~20 s) and fail LOUDLY with the diagnosable cause, rather than experiencing it as a blind result-timeout. |

### 3.5 Dependency / local-mirror implication (follow-up, not solved here)

With the coder's egress blocked, `npm install` / `uv sync` / `pip` / `dotnet restore` must resolve from a **pre-staged local mirror** (Verdaccio + wheelhouse + offline NuGet feed) the coder account can reach over loopback or a granted path — or builds fail-closed offline. Per s1ngularity this fail-closed is arguably a feature, but the mirror is a real build-out (threat-model §6 rows, P2/P3). Flagged as ACP-01's largest follow-up; scoped as its own ticket, not built inside this seam.

---

## 4. The §5.3 live proof as a standing check

The threat model makes Windows per-SID isolation **verify-not-assume** (the E8 incident is the precedent — a wrongly-scoped rule once broke the operator's machine). ACP-01 turns the proof into a repeatable script, `verify-coder-containment.ps1` (mirroring the fleet's other `verify-*.ps1` conformance scripts), that runs the probes **as the coder account** on **real spawned children** (not the launcher token — the whole point is to catch an impersonated/duplicated token that would dodge a SID-scoped rule):

1. **Outbound must fail** — from the coder account, attempt an external connection → blocked.
2. **Secret reads must be ACL-denied** — read `~/.ssh/id_*` and a file under `%LOCALAPPDATA%\BlarAI` → denied.
3. **Loopback-to-model must SUCCEED** (the added positive control) — `GET 127.0.0.1:8000/v3/models` from the coder account → 200. Catches a firewall rule so broad it kills the coder's own model access (which would silently no-op every dispatch).
4. **SID verified on the real child** — a child process spawned exactly as the dispatch spawns it emits `whoami /user`; assert it carries the `blarai-coder` SID, so the firewall rule keys on the token the coder *actually* runs under.

**Gate semantics:** this script is the **build-time gate on "(b) done"** — `[fleet_dispatch].containment = restricted_account` may not flip until it is green, and it re-runs as a standing pre-flight before each battery campaign (like the plugin canary). Until it passes, the floor is *designed, not proven* — the exact mock-safe/prod-unsafe trap the project has already been bitten by.

---

## 5. Battery safety + sequencing

**Non-negotiable:** nothing merged today may break tonight's 23:00 boot. Every ACP-01 change lands **flag-dormant** — `driver` defaults to `stdin`, `containment` defaults to `off` — so the battery runs the exact stdin/operator-account path it runs today until *both* the A/B says GO *and* `verify-coder-containment.ps1` is green. The merged code is inert until two flags flip.

**Suggested build order** (stages 1 and 2 are independent and can run in parallel):

1. **A/B-first (zero live-driver risk).** Deploy #764 (plugin-loader fix) first; run the §1 no-GPU parity probes; then the one multi-turn GPU A/B in a machine-free window. Gate: ACP clears the D-A bar, or stop. *No production code changes.*
2. **Containment substrate (independent of ACP).** Provision `blarai-coder` + ACLs + the relocated working tree + the per-SID firewall rule; write `verify-coder-containment.ps1`; run the live proof. Account/firewall/script work only — touches no live driver, flag-dormant.
3. **ACP driver behind the flag.** Build the Python ACP client beside `monitor.py`: persistent session, event→scorecard/journal mapping, `terminate_process_tree` reuse, step-cap on events, own-cancel tracking, SDK 0.11.0 pinned. Wire the `driver=acp` option; default stays `stdin`.
4. **Fuse.** Run the whole coder leg (ACP driver + opencode) as `blarai-coder` via the scheduled-task seam; orchestrator ↔ driver over the file-queue. Flip `containment=restricted_account` only after §4 is green; A/B the fused path; then cut the driver over **per run**, never rip-and-replace.

---

## 6. Open decisions (each build-defaulted, so none blocks the build)

Most of ACP-01's big calls are already made (ACP is A/B-gated per #759; containment is 1(b); hybrid-VM is the direction; Windows-guest dropped; scheduled-task-as-coder and the whole-leg-as-coder shape are HOW-calls owned here as recommendations). Three are genuinely open — but with the review gate removed, each **ships a build-default** so the builder proceeds unless the coordinator/LA overrides at review. Note D-A does not gate the build at all (the A/B runs after the flag-dormant merge); only D-B and D-C touch the containment build, and both have a safe default.

- **D-A — the A/B success bar (a capability/quality call).** The spike already proved ACP's observability, cancellation, and stall-signal are decisively better (transport-attributable); only wall-clock/token is open, and the spike's evidence suggests wall-clock is a *coder-model* property (temp-0.7 non-determinism), not a transport one. **Recommendation:** authorize the cutover on the *already-proven* event-fidelity + semantic-stall + cooperative-cancel superiority, with the multi-turn A/B required only to show **no wall-clock/token regression** — don't hold richer, safer observability hostage to a wall-clock *improvement* the confound says the transport can't deliver. (The alternative — gate cutover on a measured multi-turn wall-clock win — risks parking a strictly-safer driver on a metric it was never the lever for.)

- **D-B — relocating the coder working tree out of the operator profile (an on-disk-layout call).** Moving the throwaway worktree base to `C:\blarai-fleet\worktrees` (and granting the coder SID modify on `projects`) is mostly HOW, but it changes where dispatched code lives on disk and the merge-ownership flow, so it's flagged rather than silently taken. **Recommendation:** relocate; it lets the operator-profile default-deny do the containment heavy-lifting instead of hand-punching read-holes into `C:\Users\mrbla`. *Say so if you'd rather keep the worktree base in-profile and grant per-path instead.*

- **D-C — credential-storage posture for the de-elevated leg (a security-posture call).** Both viable launch mechanisms store the coder account's password somewhere (OS vault for the scheduled task; a DPAPI/LSA secret for `CreateProcessWithLogonW`). **Recommendation:** accept the OS-vaulted credential of the scheduled-task path — the coder account is deliberately *powerless* (no secret reads, no egress), so a leaked coder credential buys an attacker nothing the ACLs + firewall don't already contain. That powerlessness is the compensating control that makes storing the credential acceptable.

---

## 7. Build spec — anchors, contracts, definition-of-done

Concrete enough that a builder executes without re-deriving. All line numbers are 2026-07-10 anchors; the builder re-greps if the tree moved.

### 7.1 Files touched, by stage

| Stage | Surface | Anchor |
|---|---|---|
| Driver | the spawn/monitor the ACP client replaces | `agentic-setup/scripts/fleet-lib.ps1` — `Invoke-AgentRun` (spawn `:386-407`, JSON step-cap monitor `:419-461`, tree-kill `:444/:457`) |
| Driver | the per-candidate pipeline that selects the driver | `agentic-setup/scripts/new-agent-task.ps1` — `$BuildTestVerify` → `Invoke-CandidateBuild` (`:263-271`); merge/gate **unchanged** (`Test-ShouldMerge` `:508-519`) |
| Driver | the ACP client (new) | Python, beside `blarai/tools/dispatch_harness/monitor.py`; SDK `agent-client-protocol==0.11.0` (pin); reuse `blarai/shared/procspawn.py::terminate_process_tree` (`:331`, psutil-first + taskkill fallback, never raises) |
| Driver flag | fleet-side knob (NOT the BlarAI AO gate) | new `agentic-setup/configs/fleet-driver.json` (mirrors the `configs/opencode-version-pin.json` manifest pattern) → `{ "driver": "stdin", "containment": "off" }`. The BlarAI AO `[fleet_dispatch]` gate in `services/assistant_orchestrator/config/default.toml:309` stays as-is (it decides *whether* to dispatch, not *how* the coder is driven). |
| Containment | account/ACL/firewall provisioning + relocation | new `agentic-setup/scripts/provision-coder-account.ps1` |
| Containment | the standing live proof | new `agentic-setup/scripts/verify-coder-containment.ps1` (mirrors the other `verify-*.ps1` conformance scripts) |
| De-elevated leg | the scheduled-task launcher for the coder-side ACP driver | new task `\BlarAI\BlarAI-Coder-Leg`; triggered from the orchestrator via `Start-ScheduledTask`; inputs via a file-queue, results via polled files (the pattern `run-battery-night.ps1` already uses) |

### 7.2 The ACP driver's result contract (drop-in for `Invoke-CandidateBuild`)

The Python ACP client returns, and the PowerShell shim surfaces, the **exact** hashtable `Invoke-AgentRun` returns today, so `Invoke-CandidateBuild` consumes it byte-compatibly:
`@{ TimedOut; TimeoutReason; Capped; CappedReason; ExitCode; LogPath; Seconds; Error }`.
Event→field mapping the client must implement: `tool_call`/`tool_call_update` → the transcript at `LogPath` + the edit/step counts the step-cap reads; `usage_update` → token accounting; **step-cap rebuilt on events** (`Capped=true`, `ExitCode=0` at a `MaxSteps=45`-equivalent turn count + spin detector — same semantics as `Invoke-AgentRun -JsonStepCap`, easier on typed events); **idle** = "no `session/update` for ~120 s" (`TimedOut=true`, `TimeoutReason='idle'` — feeds the existing `Test-IsSamplingTerminal`/`Test-ShouldResample` idle carve-out unchanged); **cooperative cancel first, tree-kill last** (`session/cancel`, ~2.1 s; then `terminate_process_tree` for the orphaned node tree); **track own cancels** (StopReason is `end_turn` even on a cancel — the client sets its own flag, never trusts StopReason).

### 7.3 Provisioning — starting sketch (the §4 live proof is the arbiter, not this sketch)

```powershell
# Account: standard user, Users group only (NOT Administrators)
New-LocalUser -Name 'blarai-coder' -Password $sec -PasswordNeverExpires
Add-LocalGroupMember -Group 'Users' -Member 'blarai-coder'
$sid = (Get-LocalUser 'blarai-coder').SID.Value

# Relocate the throwaway worktree base out of the operator profile (D-B default);
# grant BOTH the operator and the coder SID Modify (inherited) so merge-side git can read.
# Target repos stay in C:\Users\mrbla\projects with an explicit coder-SID Modify grant.
# (icacls invocations omitted here — the builder writes them against the final paths.)

# Explicit Deny ACEs only for secret paths OUTSIDE the operator profile
# (paths under C:\Users\mrbla are already default-denied to a separate standard user).

# Per-SID outbound block (per-SID, NOT per-exe — the E8 lesson)
New-NetFirewallRule -DisplayName 'blarai-coder-deny-outbound' -Direction Outbound `
  -Action Block -Profile Any -Enabled True -LocalUser "D:(A;;CC;;;$sid)"
```

The loopback-to-OVMS path (`127.0.0.1:8000`/`:8099`) must survive this block — verified by §4 check 3, not assumed.

### 7.4 `verify-coder-containment.ps1` spec (the build-time gate on flipping `containment`)

Runs each probe **as `blarai-coder` on a real spawned child** (never the launcher token). Exit non-zero + name the failed check on any miss; the flag `containment=restricted_account` may not flip until this is green, and it re-runs as a pre-flight before each battery campaign (like the plugin canary).

1. Outbound external connect → **must fail**.
2. Read `~/.ssh/id_*` and a `%LOCALAPPDATA%\BlarAI` file → **must be ACL-denied**.
3. `GET 127.0.0.1:8000/v3/models` → **must succeed** (positive control — a too-broad rule that kills model access would silently no-op every dispatch).
4. A child spawned exactly as the dispatch spawns it emits `whoami /user` → **must carry the `blarai-coder` SID** (proves the firewall keys on the token the coder actually runs under).

### 7.5 Definition-of-done, per stage

- **Stage 1 (A/B):** #764 deployed; no-GPU parity probes green (handshake + config SHA + 0 plugin loader errors + model pinned `local/*`); one multi-turn GPU A/B run 2–3×, distribution + confound reported into `PERFORMANCE_LOG.md` + `docs/performance/` (community-grade). Verdict recorded against the D-A bar.
- **Stage 2 (containment substrate):** account + relocated tree + per-SID rule provisioned; `verify-coder-containment.ps1` **green (all 4 checks)**; flag-dormant (`containment=off`).
- **Stage 3 (ACP driver):** Python client returns the §7.2 contract; `driver=acp` path passes the same candidate-loop/gate/merge as `stdin` on a real task; `terminate_process_tree` reuse proven (0 orphaned node children after a forced timeout); step-cap + idle + own-cancel unit-tested (mirror the existing `verify-*.ps1` discipline); default stays `stdin`.
- **Stage 4 (fuse):** whole coder leg (ACP driver + opencode) runs as `blarai-coder` via the scheduled task; orchestrator↔driver over the file-queue; `containment=restricted_account` flips only after §4 green; fused path A/B'd; cutover is per-run flag, never rip-and-replace.
- **Every stage:** a `BUILD_JOURNAL.md` entry (fragment under `docs/journal_fragments/` for parallel work); flag-dormant merge so the 23:00 battery is untouched until both flags flip.

---

*This is a DRAFT — build-ready. No code, config, account, or firewall rule was created in its production. For coordinator review; on approval the build dispatches directly from §7.*
