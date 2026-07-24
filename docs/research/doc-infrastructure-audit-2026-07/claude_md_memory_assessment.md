# CLAUDE.md + MEMORY.md assessment (written by orchestrator from in-context knowledge, 2026-07-18)

## Headline math — the "effective instruction load"

The LA remembers "thousands of lines." CLAUDE.md itself never exceeded 399 lines (peak 2026-07-13,
~17.5K tokens; rewritten same day to 273 lines / ~9.6K). But the EFFECTIVE load a new interactive
session carries before doing any work:

| Component | Lines | ~Tokens | Vehicle |
|---|---|---|---|
| CLAUDE.md | 273 | 9,600 | auto-injected (every session AND every subagent) |
| MEMORY.md index | ~110 | 4,900 | auto-injected (same) |
| ACTIVE_SPRINT.md | 179 | 5,700 | mandated grounding read (measured: 15/15 full reads) |
| TEST_GOVERNANCE §1 | ~50 | ~2,600 read slice | mandated grounding read |
| git log/status + Vikunja summary | — | ~1,500 | mandated grounding calls |
| Task-named files | varies | varies | mandated |
| **Fixed floor** | **~610+** | **~24,300** | before any real work |

Plus per-ship doctrine reads: LESSONS.md search (~81K if approached naively — measured 87 reads in
last 14 days), FIELD_NOTES grep, DECISION_REGISTER append (~20K), PERFORMANCE_LOG append (~53K).
So a normal working session's doctrine-driven overhead lands ~25–100K tokens = 12–50% of context.
The LA's "thousands of lines" intuition is CORRECT about the experience, wrong only about the file.

Multiplier: 771 transcripts to date × ~14.5K injected ≈ 11M tokens of pure injection tax so far.

## CLAUDE.md section-by-section (verdict: healthy core, 4 surgical amendments)

The 2026-07-13 rewrite did its job: terse, agent-directed, dense. Do NOT diet it further for its
own sake. Amendments (all contingent on the restructure decisions, ship as one doctrine change):

1. session_start_protocol grounding item 4: points at docs/sprints/ACTIVE_SPRINT.md — the measured
   worst poison (100% full reads of 6-weeks-stale content). Retarget to the replacement live-state
   file once it exists.
2. live_state_pointers: delist docs/IMPLEMENTATION_PLAN.md (measured 0 reads ever; 103 KB dead) —
   archive the file. Keep ledger/Use Cases (cold references are fine off the hot path).
3. status_snapshot discipline is BROKEN in practice: snapshot as_of 2026-07-17 pins gate=8430 while
   TEST_GOVERNANCE (same day) says 8490 — pinned-state rot inside the doc that banned pinned state.
   Amendment: snapshot rule gains "refresh = same motion as TEST_GOVERNANCE live-figure update, or
   write NO number and point at TG §1." Consider dropping counts from snapshot entirely (pointer-only).
4. journal_discipline + performance_capture: add the rotation/index rules the restructure creates
   (journal volumes + index; perf log volumes + index; LESSONS canon/index tiers). Also maintenance
   section: add the standing size-budget line (every hot doc has a budget; breach = defect).

Explicitly KEEP as-is: authority, motto, critical_rules, user_operator, decision_boundary, autonomy,
blarai_identity, host_environment, stack, identity_split, repo_constellation, vikunja, testing,
security_by_design, git_discipline, coding_standards, context_handoff. These are live doctrine,
terse already; cutting them saves little and risks losing the control system.

## MEMORY.md index prune (MY lane — Claude-side, no LA decision needed, execute after report)

~110 entries ≈ 4.9K injected tokens. Three prune classes (target: ~55–65 entries, ~2.5K tokens):

### (a) Absorbed into CLAUDE.md 2026-07-13 rewrite — pure duplicates, RETIRE (keep file only if it
adds nuance beyond the doctrine line; most don't):
no_destructive_git_operations · no_git_add_a_in_blarai · pause_fleet_for_git_work ·
isolate_test_data_dir_from_live (LOCALAPPDATA) · comprehension_gate_stop_and_wait ·
long_outputs_to_file · spell_out_acronyms · no_commendations · cleanup_worktrees_standard +
worktree_cleanup_after_report_not_commit (merged pair → CLAUDE.md git_discipline cleanup) ·
open_vikunja_task_for_sustained_work · vikunja_ticket_decisions · never_ask_to_complete_journal ·
fold_journal_fragments_proactively · default_proven_to_live · escalate_quality_capability_decisions ·
consent_controls_own_danger · own_the_obvious_call · proactive_fix_verify_findings ·
adversarial_review_author_verifier_separation · la_does_ceremonies_for_actuals ·
automate_first_prove_human_steps · verify_alarms_before_escalating · proactive_expertise_wanted ·
verify_novice_technical_premises · throttle_background_builds · windows_paths_avoid_backslash_u ·
winui_build_invocation · isolate_build_toolchain_venv · roadmap_is_the_end ·
scrub_pollution_dont_caveat · scope_decisions_before_kickoff · calibrate_decision_asks ·
durability_needs_distribution · parallel_session_worktree_not_checkout ·
committed_not_done_until_verified_merged · merge_when_ready_and_cleanup ·
execute_dont_stop_when_goal_clear · parallelize_freely_when_dedicated (folded into autonomy) ·
default_aggressive_parallel_execution (folded into autonomy "drive don't idle")

### (b) Retired-era (cf-program / devplatform fleet / declined paths) — RETIRE or fold into one
tombstone memory ("retired worlds — do not revive"):
project_anthropic_primitive_cycle · project_cf_program_role_naming · project_cf_1_closed ·
mature_reframing_needs_sdv_amendment · manual_auditor_invocation_paused_fleet ·
ea_numbering_global · current_fleet_is_novice_mvp_not_baseline (superseded by live dispatch) ·
project_pcr_seal_verify_declined (fold into no_full_hardware_rooted_trust) ·
warn_before_screen_taking_actions (superseded by device_dedicated_dev_box) ·
reference_decision_registers (devplatform half stale; trim to BlarAI half)

### (c) Merge overlapping pairs:
uc010_illustration_model + uc010_image_generation → one · headless dispatch trio
(build_complete + code_load_boundaries + memory_namespace_pointer) → one ·
github API trio (comments_use_api + pr_review_endpoint + verify_commit_sha) → one ·
community conduct trio (engagement_first + share_promptly + collaborative_outreach +
soften_certainty) → one "upstream conduct" memory

### KEEP (live, non-doctrinal, still earning): privacy_scope · install_approved ·
ao_runtime_service_management · device schedule/overnight pair · oauth billing ·
openvino search keywords · project_context_blarai_vs_devplatform · mcp_server_processes ·
harness_kills_large_gpu_bg_tasks · 763_land_date (expires 2026-07-21) · network_facing_future ·
dispatch_containment · self_governance_boundary · coordinator_program · vision_trailer ·
model_upgrade_watch · host_mode_default · vm_topology · agent_protocol_decisions ·
public_framing + public_sync_pipeline · trust_ticket_state · autonomous_merge_authority ·
never_chain_gate_verdict · research_human_readable_reports · la_overnight_delegation ·
proactive_monitoring · context_exhaustion_self_report · stop_doomed_runs · demo capture refs ·
presented_decks_silent · security_posture_residuals · la_readily_does_ceremonies… (final list at
execution; principle: keep what CLAUDE.md does NOT already say)

## Report framing note

"Your CLAUDE.md is 273 lines and already post-diet. What you FELT was the constellation: the
mandated reads, the injected index, and the per-ship archives — an effective ~600+ lines fixed +
up to ~150K tokens of doctrine-driven reads on a working day. The satellites never got the July 13
treatment. Today they do — with size budgets so it can't regrow."
