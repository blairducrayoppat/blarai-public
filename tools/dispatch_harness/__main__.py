"""CLI for the autonomous-dispatch harness.

Examples
--------

Single LIVE dispatch (the AO must already be running — see the live-run command in the brief):

    python -m tools.dispatch_harness --repo rocket-calc --goal "a space rocket calculator" \
        --clarify-answer 1

A LIVE sweep from a JSON job file:

    python -m tools.dispatch_harness --jobs tools/dispatch_harness/examples/sweep.json

A DRY-RUN (no GPU, no live AO — a fake in-process AO drives the whole flow):

    python -m tools.dispatch_harness --dry-run --repo demo --goal "a calculator"

The LIVE path connects to the running AO at ``127.0.0.1:<vsock_port>`` (read from the AO
``default.toml``) over **production mutual-TLS** by default — the per-boot mTLS chain the launcher
provisions into ``<repo>/certs`` (ADR-026), exactly like the WinUI. It FAILS CLEARLY if those certs
are absent (BlarAI not running in production mode), if it cannot reach the AO, or if dispatch is
disabled. Pass ``--dev-mode`` to use plaintext loopback against a dev-mode AO instead. It does NOT
start the launcher/VM — start BlarAI first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from tools.dispatch_harness.config import load_harness_config
from tools.dispatch_harness.harness import DispatchHarness
from tools.dispatch_harness.jobs import JobSpec, load_jobs
from tools.dispatch_harness.report import SweepReport


def _make_console_encoding_safe() -> None:
    """Make stdout/stderr tolerate non-cp1252 characters on the Windows console.

    The coordinator's replies (and our echoes of them) carry em-dashes, ellipses, and smart
    quotes; the default Windows console code page (cp1252) raises ``UnicodeEncodeError`` on those,
    which would crash a job mid-sweep. ``reconfigure(errors="replace")`` degrades an un-encodable
    glyph to ``?`` instead of crashing — a cosmetic loss, never a functional one. Best-effort:
    a stream without ``reconfigure`` (a redirected pipe wrapper) is left as-is."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.dispatch_harness",
        description="Headless driver for the BlarAI /dispatch pipeline (the autonomous sweep).",
    )
    src = p.add_argument_group("job source (use --jobs OR --repo/--goal)")
    src.add_argument("--jobs", metavar="FILE", help="JSON sweep config (a list, or {jobs:[…]}).")
    src.add_argument("--repo", help="Single-job target repo (under the projects dir).")
    src.add_argument("--goal", help="Single-job free-text goal.")
    src.add_argument("--clarify-answer", default="",
                     help="Single-job answer to a clarifying question (number or label).")
    src.add_argument("--expected", default="",
                     help="Single-job expected outcome (MERGED/PARKED/BLOCKED/NOTHING) — report annotation only.")

    p.add_argument("--default-clarify-answer", default="1",
                   help="Default clarifying answer when a job omits one (default: 1 = first option).")
    p.add_argument("--dry-run", action="store_true",
                   help="Run the full flow against a FAKE in-process AO (no GPU, no live AO).")
    p.add_argument("--dry-run-ambiguous", action="store_true",
                   help="In --dry-run, make the fake AO return an AMBIGUOUS plan so the Inc-4 "
                        "clarifying-question path is exercised (the harness answers it).")
    p.add_argument("--config", metavar="TOML",
                   help="Override the AO default.toml path (port + fleet roots are read from it).")
    p.add_argument("--session-id", default="harness", help="Session id for the dispatch turns.")

    live = p.add_argument_group("LIVE transport (production mTLS by default)")
    live.add_argument("--dev-mode", action="store_true",
                      help="Connect to a dev-mode AO over PLAINTEXT loopback (no mTLS). Default is "
                           "OFF — LIVE uses the per-boot production mTLS chain the launcher writes "
                           "to <repo>/certs (ADR-026), exactly like the WinUI.")
    live.add_argument("--certs-dir", metavar="DIR",
                      help="Override the per-boot certs directory (default: <repo>/certs). "
                           "Ignored with --dev-mode.")

    mon = p.add_argument_group("monitoring (stop-doomed-fast)")
    mon.add_argument("--poll-interval-s", type=float, default=5.0,
                     help="Seconds between progress polls (default: 5).")
    mon.add_argument("--stall-grace-s", type=float, default=240.0,
                     help="No-progress window that defines a doomed run (default: 240).")
    mon.add_argument("--overall-timeout-s", type=float, default=0.0,
                     help="Hard per-run cap (default: 0 = use the AO's swap_run_budget_s).")

    p.add_argument("--report-json", metavar="FILE",
                   help="Write the machine-readable sweep report to this file.")
    return p


def _resolve_jobs(args: argparse.Namespace) -> list[JobSpec]:
    if args.jobs:
        return load_jobs(args.jobs, default_clarify_answer=args.default_clarify_answer)
    if args.repo and args.goal:
        return [
            JobSpec(
                repo=args.repo.strip(),
                goal=args.goal.strip(),
                clarify_answer=(args.clarify_answer or "").strip() or args.default_clarify_answer,
                expected=(args.expected or "").strip().upper(),
            )
        ]
    raise SystemExit(
        "error: provide either --jobs FILE or both --repo and --goal "
        "(see --help)."
    )


def _build_dry_run_harness(args: argparse.Namespace, config) -> DispatchHarness:
    """A self-contained fake AO: a clear-surface plan + an execute_fn that writes a fake SUMMARY
    into a temp runs dir, so the monitor returns COMPLETE with no model and no live AO."""
    import tempfile

    from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult
    from shared.fleet.dispatch import FleetDispatchConfig

    tmp = Path(tempfile.mkdtemp(prefix="dispatch-harness-dryrun-"))
    fake_config = FleetDispatchConfig(
        scripts_dir=tmp / "scripts",
        queue_path=tmp / "state" / "fleet-queue.json",
        runs_dir=tmp / "state" / "fleet-runs",
        projects_dir=tmp / "projects",
    )

    ambiguous = bool(getattr(args, "dry_run_ambiguous", False))

    def _spec(goal: str) -> AcceptanceSpec:
        if ambiguous:
            build_plan = {"surface": "ambiguous", "language_hint": None,
                          "complexity": "moderate", "components": [],
                          "candidates": ["desktop-gui", "web", "mobile"]}
        else:
            build_plan = {"surface": "desktop-gui", "language_hint": None,
                          "complexity": "moderate", "components": []}
        return AcceptanceSpec(
            goal,
            (
                AcceptanceCriterion("c1", "the project builds", "build", ""),
                AcceptanceCriterion("c2", "the headline feature works", "behavior", ""),
            ),
            build_plan=build_plan,
        )

    async def plan_fn(repo: str, goal: str) -> PlanResult:
        spec = _spec(goal)
        return PlanResult(
            ok=True,
            tasks=[{"repo": repo, "task": "build-it", "prompt": "build it",
                    "surface": spec.build_plan["surface"]}],
            spec=spec,
            message="planned (dry-run)",
        )

    async def execute_fn(session_id, run_id, repo, tasks, spec):
        from shared.fleet.dispatch import DispatchResult

        run_dir = fake_config.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "SUMMARY.txt").write_text(
            f"Fleet run {run_id} — 1 task(s):\n"
            "- build-it: processed\n"
            "    RESULT: MERGED into your project - just open the app and try it.\n",
            encoding="utf-8",
        )
        return DispatchResult(
            ok=True, run_id=run_id,
            message=f"Dispatching {run_id} — 1 task(s) to the coder fleet (dry-run).",
        )

    return DispatchHarness.for_dry_run(
        config=fake_config,
        plan_fn=plan_fn,
        execute_fn=execute_fn,
        session_id=args.session_id,
        default_clarify_answer=args.default_clarify_answer,
    )


def main(argv: list[str] | None = None) -> int:
    _make_console_encoding_safe()
    args = _build_parser().parse_args(argv)
    jobs = _resolve_jobs(args)

    cfg = load_harness_config(args.config)
    overall_timeout = args.overall_timeout_s or cfg.swap_run_budget_s

    if args.dry_run:
        harness = _build_dry_run_harness(args, cfg)
        print("DRY-RUN: driving the full /dispatch flow against a fake in-process AO.\n")
    else:
        if not cfg.fleet_dispatch_enabled:
            print(
                f"WARNING: [fleet_dispatch].enabled is false in {cfg.config_path}.\n"
                "         The running AO is the source of truth; if it was started with dispatch\n"
                "         disabled, every /dispatch will return the disabled notice.\n",
                file=sys.stderr,
            )
        harness = DispatchHarness.for_live(
            port=cfg.port,
            agentic_setup_dir=cfg.agentic_setup_dir,
            projects_dir=cfg.projects_dir,
            fleet_dispatch_enabled=cfg.fleet_dispatch_enabled,
            dev_mode=args.dev_mode,
            certs_dir=args.certs_dir,
            session_id=args.session_id,
            default_clarify_answer=args.default_clarify_answer,
            poll_interval_s=args.poll_interval_s,
            stall_grace_s=args.stall_grace_s,
            overall_timeout_s=overall_timeout,
        )
        _transport = "PLAINTEXT loopback (dev-mode)" if args.dev_mode else "loopback + production mTLS"
        print(
            f"LIVE: connecting to the AO at {cfg.host}:{cfg.port} over {_transport} "
            f"(roots: {cfg.agentic_setup_dir or 'default'} / {cfg.projects_dir or 'default'}).\n"
            f"Monitoring: poll {args.poll_interval_s:.0f}s, stall-grace {args.stall_grace_s:.0f}s, "
            f"overall cap {overall_timeout:.0f}s.\n"
        )

    sweep: SweepReport = asyncio.run(harness.run_sweep(jobs))

    print("\n" + sweep.render() + "\n")
    if args.report_json:
        Path(args.report_json).write_text(sweep.to_json(), encoding="utf-8")
        print(f"(machine-readable report written to {args.report_json})")

    # Exit non-zero if any job did not complete cleanly (useful for scripting the sweep).
    failed = sum(1 for j in sweep.jobs if j.verdict != "COMPLETE")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
