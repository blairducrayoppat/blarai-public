# Guide Workstream Registry — BlarAI

This directory hosts BlarAI-side Guide-coordinated workstreams per
`devplatform/docs/governance/guide-agent-design.md`. Each row is one workstream;
click into `<slug>/` for the charter, STATUS log, and per-phase artifacts.

## Registry

| Slug | State | LA | Guide | Started | Closed | Vikunja | Description |
|---|---|---|---|---|---|---|---|
| [openvino-contribution-npu-int8-guard](openvino-contribution-npu-int8-guard/) | Active | Blair | Guide-#11 | 2026-05-12 | — | #443 | OpenVINO upstream contribution targeting issue [#35641](https://github.com/openvinotoolkit/openvino/issues/35641) — NPU LLMPipeline silently accepts INT8 weight-only IR and crashes uncatchable at `generate()`; engagement uses PR [#34651](https://github.com/openvinotoolkit/openvino/pull/34651) as the construct-time-guard precedent template |
| [openvino-upstream-shepherding](openvino-upstream-shepherding/) | Active | Blair | Guide-#11 | 2026-05-12 | — | #466 | Continuous shepherding of LA's open OpenVINO upstream PRs/issues — state monitoring, follow-up drafting, retests when upstream versions change, cadence management. Companion to (not replacement for) the deeper `-int8-guard` workstream. |

## State values

| State | Meaning |
|---|---|
| `Active` | Currently executing phases |
| `Complete` | All planned phases passed; closure declared in workstream STATUS.md |
| `Archived` | Historically complete; moved to `archive/<slug>/` |
| `Deferred` | Paused mid-execution; not abandoned (resume condition recorded in workstream README) |

See `devplatform/docs/governance/guide-agent-design.md` §Workstream States for
transition rules and §Migration From Legacy Layout for the relationship to
Stage 6.7.5 artifacts (those remain at `docs/platform_separation/` and are not
listed in this registry).

## Numbering

Guide instances and EA instances are **globally numbered** across project
history (per BlarAI memory notes "EA numbering is global, not stage-scoped" and
the guide design doc §Numbering and Ack Convention).

- Guide-#10: Stage 6.7.5 hardening (2026-05-07 to 2026-05-08, EA-10 through EA-16)
- Guide-#11: this workstream (started 2026-05-12, EA-17+)
