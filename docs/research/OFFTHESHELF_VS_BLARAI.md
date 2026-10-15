---
title: Off-the-shelf products versus BlarAI and the Governator (2026-10-11)
status: living
area: research
---

# Off-the-shelf products versus BlarAI and the Governator

*Plain summary: the Lead Architect (LA) asked whether a larger team is already building what he needs, and whether he should use off-the-shelf products instead, after watching a Microsoft Build 2026 clip (session clip transcript: `docs/research/windows-containment-comparison-2026-10/sources/ms-build-2026-j7ol1vdkg7w/`) about OpenClaw on Windows. Five read-only studies with five independent skeptic checks were run on 2026-10-11. The raw studies and the skeptic findings are in `C:/blarai-spike-1740-mxc/study-offshelf/` and the workflow journal; this document is the synthesis, with every skeptic correction applied.*

## 1. The answer, outcome first

1. **No single product, and no sensible combination, meets the whole requirement set today** (privacy-first with no telemetry, locally run on the Intel Arc and NPU laptop, secure, with BlarAI's encrypted storage, signed models and gated egress). Several layers of BlarAI are commodity and are already built on off-the-shelf parts (OpenVINO GenAI and its model server, opencode, open Qwen3 weights). The layers that define BlarAI's trust are not available off the shelf.
2. **The video shows less than it seems.** It shows one demo: an agent told to delete the Desktop is stopped by a read-only folder rule inside Microsoft's container (MXC process isolation). The presenter says the demo had "turned off all of the many layers OpenClaw offers", so the container alone did the work. The video says nothing about telemetry, local models, encryption or prompt-injection defence, and calls the Windows companion app an alpha.
3. **The Governator is the project most exposed.** Microsoft's open-source Agent Governance Toolkit (AGT, MIT licence, version 5.0.0 "Public Preview", created 2026-03-02) already ships Claude Code and Codex CLI plugins that run a policy check before each tool call and keep a hash-chained log. That is the Governator's main mechanism. This is read from source, not run. What AGT does not appear to offer is in section 7.
4. **Your telemetry hypothesis is partly right and partly wrong.** The Windows companion app has no analytics code; it checks GitHub for updates at startup (off with `OPENCLAW_SKIP_UPDATE_CHECK=1`). The OpenClaw gateway it installs does phone home daily by default. See section 3.
5. **A privacy defect was found in BlarAI's own environment and fixed the same day** (section 6).

## 2. What the video does and does not show

Read in full (8.8 minutes). Shown: a WinUI 3 companion app that sandboxes OpenClaw's shell-command tool with MXC; folder read-only/write/hidden settings; clipboard and internet toggles; "IT policy" said to be settable; the OpenClaw creator describing observability, auto-mode permissions, a pluggable harness (Copilot, Codex), persistent memory, heartbeats, Slack and Teams. Not shown or stated: any telemetry fact, any model hosting, any encryption, any injection defence. The creator's own line, "I built OpenClaw to have access to everything", describes the default posture, and the new permission model is how they made it acceptable to companies.

From the companion app's source (main commit 16299381, 2026-10-11, MIT, alpha): the sandbox wraps only the shell-command tool on the Windows node; the browser, camera, screen capture, model gateway and the gateway itself are outside it; if the sandbox cannot start, the app by default runs the command unprotected (an open change, #1618, would stop that; not shipped); no Intune, Group Policy or registry policy code exists, and the demo's "IT policy" is a local settings file the same user can edit; the shipped MXC version is 0.8.0, not the 1.0.0 studied in #1740. On this laptop the container's default graphics lockdown stops node, git and Python from starting (the #1740 arm E result), git-bash failed even with it relaxed, and the companion's own local-model feature is built around llama.cpp with NVIDIA CUDA, not Intel Arc or OpenVINO.

## 3. Telemetry audit (source read; closed-source products cannot be audited)

| Product | Finding | Evidence kind |
|---|---|---|
| OpenClaw gateway | Daily request to `telemetry.openclaw.ai` carrying version, OS, Node version, CPU architecture; the service records Cloudflare-derived country, region, city and timezone for 3 months; `DO_NOT_TRACK` does not stop it. Also a default model-catalog refresh from `catalog.openclaw.ai` and plugin/skill feeds from `clawhub.ai`. Off with `update.checkOnStart=false`, `models.catalogRefresh.enabled=false`. No usage analytics SDK found in core. | source read, skeptic-confirmed |
| OpenClaw Windows companion | No analytics SDK. OpenTelemetry export exists but is off until an endpoint is entered. Startup update check against GitHub (off with the environment variable; no in-app switch found). WebView2 and Windows platform telemetry not examined. A "Native Gateway" install sets the gateway opt-out automatically; the WSL install path does not. | source read |
| MXC | Telemetry off unless the caller turns it on and the user consents; the companion's config never sets it. Inferred from source and package, not measured at run time. | source read |
| Foundry Local | Telemetry on by default per its own privacy page; opt-out switches exist. | vendor document |
| Ollama (Windows) | Hourly update check with auto-update on by default (sends OS, architecture, version, a signed nonce); no analytics code found; a survey setting was not examined. | source read |
| Open WebUI | Update check on unless offline mode is set; Docker image sets no-analytics variables. | source read |
| AnythingLLM | Usage events to PostHog unless `DISABLE_TELEMETRY=true`. | source read |
| Jan | In-app analytics off until consent, but its updater calls an analytics-proxy endpoint with a session value, so "off until consent" is not established. | source read, skeptic correction |
| LM Studio, Claude Code, Copilot CLI | Closed source: cannot be audited here. | n/a |
| OpenVINO toolchain on this machine | **Google Analytics telemetry** in the `openvino-telemetry` package, used by the NNCF compression library, defaults to ON when no consent file exists. Fixed locally (section 6). | source read plus files on disk |
| AGT plugins | No network calls in the Claude Code and Codex plugin directories (repo-wide grep widened by the skeptic); elsewhere network code is feature-specific. The hosts those plugins govern are cloud-model clients. | source read |

## 4. OpenClaw's security record (corrected)

The first study reported about 3,600 advisories (2,700 in September 2026). That was a paging error: the advisory interface ignores the page number, so the same 100 records were read 36 times. The skeptic's recount: **722 advisories in about nine months, 14 critical, 249 high, 39 with a CVE number, peaking February to April 2026**. The project's own policy says it is built for one trusted operator and that prompt injection alone is not a vulnerability; sandboxing is off by default; its secret store is documented as not encrypted at rest; its docs say not to use small models for tool-enabled agents, which is the tier a local 14B model sits in. A third-party skill marketplace (ClawHub) had malicious skills reported in early 2026 (secondary reporting only). How many advisories were fixed and whether the rate is falling was not checked.

## 5. Layer by layer: adopt, keep building, or watch

| Layer | BlarAI today | Off-the-shelf position | Verdict |
|---|---|---|---|
| Inference runtime | OpenVINO GenAI with speculative decoding, OpenVINO Model Server for the coder; about 4.2k lines of glue | OpenVINO is itself the off-the-shelf choice. Other tools use llama.cpp Vulkan or SYCL paths; no OpenVINO or NPU path found in Ollama, Jan or OpenClaw | **Already adopted.** Speed comparison is not shown either way (see below) |
| Model | Open Qwen3-14B weights | Open weights | **Commodity, already adopted** |
| Agent loop, tool dispatch | About 30k lines | OpenClaw has comparable features, but its safety stance depends on a frontier-tier model; its gateway phones home by default | **Keep, watch.** Not adoptable under the telemetry and small-model conditions |
| Tool sandbox | None for the assistant; account-level for the coder | MXC, AppContainer, Codex's Windows sandbox are the commodity direction | **Watch closely.** #1740 showed they cannot yet host the coder; the #1406 probe now shows a route (section 8) |
| Policy gate (the single adjudication door) | About 14.6k lines; live core is a deterministic checker (about 300 lines, not 150) plus output validation and the egress locks | Nothing surveyed sits in this position (inside a local-only system) | **Distinctive. Keep.** AGT is worth learning from and measuring against |
| Born-encrypted storage with hardware keys | Yes | OpenClaw's store is unencrypted; Open WebUI has an optional encrypted database | **Distinctive. Keep** |
| Signed model manifests verified at boot | Yes | Not found in Ollama, Jan, Open WebUI, AnythingLLM, OpenClaw | **Distinctive. Keep** |
| Per-scope policy-gated egress with ceremonies | Yes | Not found | **Distinctive. Keep** |
| Hash-chained audit | Yes | AGT has an unkeyed hash chain (its README says not proof against someone who can rewrite it) | **Keep; compare** |
| Chat UI and generic document search | WinUI 3 app; own ingestion | Open WebUI, AnythingLLM, Jan cover the function; none verified against the privacy rule | **Commodity in function; adopt only after a telemetry audit of the exact build** |
| Voice, image generation | Whisper on GPU; local SDXL | Whisper and ComfyUI-based tools exist (Intel AI Playground) | **Commodity in principle; low effort in the code (about 2.4k lines together)** |
| Coder fleet | About 74.6k lines | The agent (opencode) and model server are already off the shelf; the cloud coding CLIs fail "zero outbound network" | **Keep.** The bespoke part is grading and gating machinery |

**Where the build effort sits (measured lines of code, not hours; 205k of 285k code lines mapped by path rules, main `b93b340e`):** coder fleet 36%, performance measurement 19%, agent loop and launcher 15%, memory and storage 9%, policy gate 7%, UI 6%, inference 2%, audit 2%, model integrity 2%, image 1%. The layers that make BlarAI trustworthy are small; the large ones are the coder machinery and the measurement tooling.

**Speed.** The first study said BlarAI's 14B model is faster than competitors' 7B to 9B models. The skeptic showed the 25 tokens per second figure is a 16-token run at a short prompt. Like for like: 13.9 tokens per second with speculative decoding, 8.7 without, 10.4 at a 6,000-token prompt. The competitor numbers are from other chips, systems and model sizes. **No speed ordering is established in either direction.**

## 6. A defect found and fixed: OpenVINO telemetry on this machine

The OpenVINO telemetry package defaults to sending usage data (via Google Analytics) when no consent file exists; the NNCF model-compression library starts it without a prompt. On this machine no consent file existed, a Google Analytics client ID file was created 2025-10-20, and a usage counter was last updated 2026-10-09. This affects model conversion and compression, not live inference. **Fixed 2026-10-11:** the local consent file `%LOCALAPPDATA%\Intel Corporation\openvino_telemetry` now holds `0` (declined); both Python environments that import the package (`.venv` and the image-conversion environment) read "declined". The official opt-out command may send a final event, so the file was written directly. **Not known:** whether data left the machine in the past (no network capture was made). **Open:** a permanent control (a check that fails if any build environment lacks the opt-out), tracked on ticket #1748; the BlarAI rule is no big-tech services without approval.

## 7. The Governator

AGT covers the hook seam. Differences the study could not find a competitor claiming, each weaker than first stated: (1) one resident, person-owned governor across several agents; (2) a coverage screen with "Unknown" as the default status, which reports its own absence. The skeptic found AGT ships an agent-discovery package with an UNKNOWN status, so (2) is only a partial difference; (3) a log whose head is signed by the machine's security chip (no use of one found in AGT's plugins). AGT's own documented limits are the same ones the Governator records: fail-open on timeout, Codex skipping hooks until trusted, no coverage of shell-in-shell commands, so it is a policy aid and not containment. AGT governs agents whose prompts already go to the cloud, a different threat model from BlarAI's local-only one.

**Conditions that would make finishing the Governator worth it** (all observable; this is inference): (a) run AGT's plugin on this machine through the Governator's own P1 to P6 tests; if it behaves like the Governator's hook client, the hook seam is adopt-not-build; (b) check whether Microsoft ships a cross-agent coverage view where unprotected agents show as Unknown; (c) check whether Windows agent identity or MXC's policy layer reaches non-enterprise Windows 11; (d) check whether a non-Microsoft program can register in Windows's agent-protocol slot. Worth finishing only if (a) leaves a real gap, (b) has not happened, and (c) and (d) are still open. Otherwise the honest outcome is to adopt AGT as the hook layer and keep the coverage-honesty vocabulary and the BlarAI integration. Nothing here has been run.

## 8. What the #1406 probe adds (same day)

The study noted that Codex's own MXC sandbox crate documents allowing loopback clients, which conflicted with the #1740 localhost refusal. The probe of MXC pull request #1406 (self-built from main, commit 70fc7d52, because no signed release has it) reconciles them: with the "unpackaged proxy" configuration, a container reached a listener on 127.0.0.1:18099 in 3 of 3 runs while the other loopback port, the LAN address and the internet stayed blocked (6 further launches rejected by the launcher as expected). Section 8 of the report `docs/research/windows-containment-comparison-2026-10-10.md` is not updated for this yet; the probe is under independent review and its README is `docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/` once merged. Caveats already known: DNS resolution worked inside the container while connecting stayed blocked (a possible side channel, untested); a self-built unsigned build from main; one machine and build; IPv4 TCP only.

## 9. What is not known

OpenClaw running against a local OpenVINO endpoint on this laptop; whether either stack resists prompt injection with a local 14B model (BlarAI's own 14B injection numbers are recorded as retracted); Foundry Local on this NPU; Windows and WebView2 platform telemetry; real network traffic of any product (everything above is from source and documents, nothing was installed or captured); AGT run on this machine; Jan's and Ollama's complete network behaviour; the model-integrity and advisory history of the local-stack products.

## 10. Decisions that are the LA's

1. **Governator direction.** Recommendation: do not decide yet. Authorise the four observable tests in section 7 (about a day of work, no cost), then choose among finishing it, adopting AGT as the hook layer and keeping only the coverage vocabulary, or pausing it.
2. **A bounded OpenClaw trial** (in a throwaway virtual machine, local model only, all default calls switched off, network captured). Recommendation: not now; the privacy and small-model findings say it cannot be the agent core, and nothing in it covers the trust layers. Revisit if the trial question is "what can the companion's sandbox idea teach the assistant's shell tool".
3. **Whether to put the openvino opt-out into a permanent check** (recommended; small).

## 11. Artifacts read

OpenClaw and companion source archives (v2026.10.1 and main 16299381), MXC 0.8.0 and 1.0.0 packages, Ollama, Jan, Open WebUI, AnythingLLM, Foundry Local, llama.cpp, OVMS repository (the source folder was empty, so its telemetry was not checked), AGT repository, Pipelock repository, Codex's mxc-sandbox crate, the OpenVINO telemetry package on this machine, the video transcript, BlarAI and Governator repositories. Closed-source products and Microsoft's Defender and Agent 365 pages rest on third-party or vendor text only.
