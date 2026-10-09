"""Probe: thinking control on the Qwen3.6-35B-A3B, through the real eval harness (#1611 S0c).

WHAT THIS SETTLES
-----------------
The 2026-07-17 answer-quality run of the 35B-A3B scored 22/40, and **10 of its
18 failures were ``no_think_tags``** — the model emitted a reasoning block the
production strip could not remove. That result has gated #930 ever since. This
probe asks whether the blocker is a property of the model or an artifact of how
the July run built its prompt.

THE MECHANISM, read from the model's own chat template
------------------------------------------------------
``chat_template.jinja`` lines 171-175 of the official export::

    {%- if enable_thinking is defined and enable_thinking is false %}
        {{- '<think>\\n\\n</think>\\n\\n' }}      <- the EMPTY block: no-think
    {%- else %}
        {{- '<think>\\n' }}                      <- a BARE OPEN: forces thinking
    {%- endif %}

The July run reached the model through ``evals.hardware_pipeline``, which hands
``VLMPipeline.generate`` a hand-built ChatML string with
``GenerationConfig.apply_chat_template`` left at its default ``True`` and no
``enable_thinking`` anywhere. The template therefore took the ``else`` branch
and appended a bare ``<think>\\n``: the July eval did not merely fail to
suppress thinking, it *asked for it*, on every case, and then scored the model
for complying.

THE ARMS (the plan's D / A / B; C only if all three fail)
---------------------------------------------------------
* **D** — the production recipe. ``wrap_chatml`` + the empty block appended by
  hand, with ``apply_chat_template=False`` set EXPLICITLY so the template
  cannot wrap the string a second time. This is byte-identical to what the
  Policy Agent already ships (``services/policy_agent/src/gpu_inference.py``).
* **A** — ``ChatHistory`` + ``set_extra_context({"enable_thinking": False})``,
  the API the runtime provides for exactly this.
* **B** — ``set_chat_template`` with the condition inverted so no-think is the
  DEFAULT. Mutates the pipeline, so this arm runs LAST.
* **C** — wrapper-side strip. Measured only if D/A/B all fail, and recorded as
  a fallback that was measured, never as one that was adopted.

WHY THE FIRST-TOKEN WITNESS IS DIRECT AND NOT A PROXY
-----------------------------------------------------
ADR-012 §2.4 lesson 6: GenAI suppresses stop-token checks for ids already in
the input, so with the empty block present the think ids can never be stop
targets — the model must simply decline to open a new block. The gate is
therefore "the first generated token is not ``<think>``". ``VLMDecodedResults``
exposes no raw token ids, so this probe reads the first chunk handed to a
streamer callback. That is a faithful witness rather than a proxy, and the
probe PROVES the equivalence at run time before trusting it: it asserts
``encode("<think>") == [248068]`` (a single id) and ``decode([248068]) ==
"<think>"`` (not skipped as a special token). Both are recorded in the output
JSON. If either fails the probe refuses to score the first-token gate.

DENOMINATOR CORRECTION (#1611 / #1610 as written said "39/40")
--------------------------------------------------------------
``evals/golden/answer_quality.jsonl`` holds 40 cases, but **21 are ``offline``
fixtures** scored against static exemplar strings with no model in the loop;
only **19 are ``model`` mode**. A first-token gate over "40" is unmeasurable:
21 of those cases never generate a token. The gate here keeps the plan's
one-case tolerance and applies it to the real denominator: **>= 18 of 19**.
The suite-level counts (pass rate, ``no_think_tags`` failures) remain over all
40, which is what the July 22/40 figure is comparable against.

Usage::

    .venv/Scripts/python scripts/probe_35b_thinking_control.py
    .venv-2026.4/Scripts/python scripts/probe_35b_thinking_control.py --runtime-label 2026.4.0

The model loads ONCE and every arm reuses it: three loads of an 18.6 GB export
would spend ~2.5 minutes of GPU window on nothing, and the arms differ only in
how the prompt is built.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_MODEL_DIR = "B:/models/Qwen3.6-35B-A3B-int4-ov"

# Verified against the tokenizer at run time before the gate is scored.
THINK_OPEN_ID = 248068
THINK_OPEN_TEXT = "<think>"
EMPTY_THINK_BLOCK = "<think>\n\n</think>\n\n"
ASSISTANT_HEADER = "<|im_start|>assistant\n"

# The two cases whose rubric anchors the answer to the very first character —
# a leading reasoning block breaks them even when the answer itself is right.
START_ANCHOR_CASES = ("aq-form-mod-01", "aq-form-mod-03")

# The template's thinking branch, and the patch that makes no-think the default.
TEMPLATE_COND = "{%- if enable_thinking is defined and enable_thinking is false %}"
TEMPLATE_COND_NOTHINK_DEFAULT = (
    "{%- if not (enable_thinking is defined and enable_thinking is true) %}"
)


def _fail(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)


def verify_think_token_mapping(tokenizer: Any) -> dict[str, Any]:
    """Prove the streamer's first chunk is a faithful witness of the first token.

    Returns a record of the check. ``usable`` is False when ``<think>`` is not
    a single token or does not survive detokenization — in which case the
    first-token gate is reported as UNMEASURABLE rather than guessed at.
    """
    record: dict[str, Any] = {
        "expected_id": THINK_OPEN_ID,
        "usable": False,
        "error": None,
    }
    try:
        encoded = tokenizer.encode(THINK_OPEN_TEXT).input_ids.data.flatten().tolist()
        decoded = tokenizer.decode([THINK_OPEN_ID])
        record["encode_think_open"] = encoded
        record["decode_248068"] = decoded
        record["usable"] = encoded == [THINK_OPEN_ID] and decoded == THINK_OPEN_TEXT
    except Exception as exc:  # noqa: BLE001 — a probe never dies on its own check
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def inspect_rendered_prompt(prompt: str) -> dict[str, Any]:
    """Describe a rendered prompt the way the gate needs to read it."""
    return {
        "chars": len(prompt),
        "assistant_headers": prompt.count(ASSISTANT_HEADER),
        "empty_think_blocks": prompt.count(EMPTY_THINK_BLOCK),
        "ends_with_bare_think_open": prompt.rstrip().endswith(THINK_OPEN_TEXT),
        "system_headers": prompt.count("<|im_start|>system\n"),
        "tail": prompt[-160:],
    }


def _prompt_is_well_formed(info: dict[str, Any]) -> bool:
    """One assistant turn, one empty think block, no bare open left dangling."""
    return (
        info["assistant_headers"] == 1
        and info["empty_think_blocks"] == 1
        and not info["ends_with_bare_think_open"]
    )


class ArmResult:
    """One arm's measured evidence."""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.rendered_prompt: str | None = None
        self.prompt_info: dict[str, Any] | None = None
        self.first_chunks: list[dict[str, Any]] = []
        self.error: str | None = None
        self.suite: dict[str, Any] | None = None
        self.wall_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.name,
            "description": self.description,
            "rendered_prompt_first_case": self.rendered_prompt,
            "rendered_prompt_inspection": self.prompt_info,
            "first_chunks": self.first_chunks,
            "generations": len(self.first_chunks),
            "wall_seconds": round(self.wall_seconds, 1),
            "error": self.error,
            "suite": self.suite,
        }


def build_arm_generator(
    pipe: Any,
    tokenizer: Any,
    ov_genai: Any,
    arm: str,
    *,
    system_prompt: str,
    max_new_tokens: int,
    result: ArmResult,
    strip_thinking: bool = False,
) -> Callable[[str], str]:
    """Return the suite's ``Callable[[str], str]`` generator for one arm.

    The composed context arrives exactly as production builds it (the suite
    drives the real ``ContextManager``); each arm differs only in how that
    context becomes a prompt.
    """
    from evals.hardware_pipeline import wrap_chatml

    def _render(composed: str) -> tuple[Any, dict[str, Any]]:
        """Build (prompt_or_history, generate_kwargs) for this arm."""
        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = max_new_tokens
        cfg.do_sample = False  # greedy / temperature-0 — reproducible

        if arm in ("D", "C"):
            # The production recipe: hand-built ChatML carrying the empty
            # block, and the template explicitly forbidden from wrapping again.
            prompt = wrap_chatml(system_prompt, composed) + EMPTY_THINK_BLOCK
            cfg.apply_chat_template = False
            return prompt, {"generation_config": cfg}

        if arm == "A":
            history = ov_genai.ChatHistory()
            history.append({"role": "system", "content": system_prompt})
            history.append({"role": "user", "content": composed})
            history.set_extra_context({"enable_thinking": False})
            return history, {"generation_config": cfg}

        if arm == "B":
            # Template already swapped on the pipeline; let it render.
            prompt = composed
            cfg.apply_chat_template = True
            return prompt, {"generation_config": cfg}

        raise ValueError(f"unknown arm {arm!r}")

    def _render_for_dump(composed: str) -> str:
        """What the runtime will actually feed the model, for the dump."""
        if arm in ("D", "C"):
            return wrap_chatml(system_prompt, composed) + EMPTY_THINK_BLOCK
        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": composed},
        ]
        if arm == "A":
            return tokenizer.apply_chat_template(
                msgs, True, extra_context={"enable_thinking": False}
            )
        return tokenizer.apply_chat_template(msgs, True)

    def generate(composed_context: str) -> str:
        if result.rendered_prompt is None:
            try:
                rendered = _render_for_dump(composed_context)
                result.rendered_prompt = rendered
                result.prompt_info = inspect_rendered_prompt(rendered)
            except Exception as exc:  # noqa: BLE001
                result.prompt_info = {"render_error": f"{type(exc).__name__}: {exc}"}

        target, kwargs = _render(composed_context)

        chunks: list[str] = []

        def streamer(chunk: str) -> Any:
            if len(chunks) < 4:
                chunks.append(chunk)
            return ov_genai.StreamingStatus.RUNNING

        t0 = time.perf_counter()
        try:
            out = pipe.generate(target, streamer=streamer, **kwargs)
        except Exception as exc:  # noqa: BLE001 — fail-closed, recorded per case
            raise RuntimeError(f"[arm {arm}] generation failed: {exc}") from exc
        elapsed = time.perf_counter() - t0

        text = str(out)
        first = chunks[0] if chunks else ""
        result.first_chunks.append(
            {
                "first_chunk": first,
                "opened_think": first.strip() == THINK_OPEN_TEXT
                or first.startswith(THINK_OPEN_TEXT),
                "leading_chunks": chunks[:3],
                "seconds": round(elapsed, 2),
                "output_head": text[:90],
            }
        )

        if strip_thinking:  # arm C only — measured, never adopted
            marker = "</think>"
            if marker in text:
                text = text.split(marker, 1)[1].lstrip("\n")
        return text

    return generate


def score_arm(result: ArmResult, mapping_usable: bool) -> dict[str, Any]:
    """Apply the S0c gate to one arm's evidence."""
    gate: dict[str, Any] = {}
    suite = result.suite or {}
    agg = suite.get("aggregates", {})
    failures = suite.get("failures", [])

    no_think_failures = [f for f in failures if f.get("failed_check") == "no_think_tags"]
    gate["no_think_tag_failures"] = len(no_think_failures)
    gate["no_think_tag_failures_pass"] = len(no_think_failures) == 0

    failed_ids = {f["id"] for f in failures}
    gate["start_anchor_cases"] = {
        cid: ("pass" if cid not in failed_ids else "fail") for cid in START_ANCHOR_CASES
    }
    gate["start_anchor_pass"] = all(c not in failed_ids for c in START_ANCHOR_CASES)

    info = result.prompt_info or {}
    gate["prompt_well_formed"] = bool(info) and _prompt_is_well_formed(info)

    generations = len(result.first_chunks)
    clean = sum(1 for c in result.first_chunks if not c["opened_think"])
    gate["first_token_clean"] = clean
    gate["first_token_total"] = generations
    if not mapping_usable:
        gate["first_token_pass"] = None
        gate["first_token_note"] = (
            "UNMEASURABLE: the <think> token/text mapping did not verify, so the "
            "streamer's first chunk is not a sound witness of the first token id."
        )
    elif generations == 0:
        gate["first_token_pass"] = None
        gate["first_token_note"] = "UNMEASURABLE: no generations completed."
    else:
        # The plan's one-case tolerance, on the real model-mode denominator.
        gate["first_token_pass"] = clean >= generations - 1
        gate["first_token_note"] = (
            f"{clean}/{generations} model-mode generations did not open a think "
            f"block (tolerance: 1). NOTE the written gate said 39/40; the golden "
            f"file's other 21 cases are offline fixtures that never reach the model."
        )

    gate["pass_rate"] = agg.get("pass_rate")
    gate["passed"] = agg.get("passed")
    gate["total"] = agg.get("total")

    hard = [
        gate["no_think_tag_failures_pass"],
        gate["start_anchor_pass"],
        gate["prompt_well_formed"],
        gate["first_token_pass"],
    ]
    gate["ARM_PASSES"] = all(x is True for x in hard)
    return gate


def summarize_report(report: Any) -> dict[str, Any]:
    """Flatten a SuiteReport into the JSON record, keeping every failure."""
    from evals.types import CaseStatus

    results = list(report.results)
    failures = [
        {
            "id": r.case_id,
            "detail": r.detail,
            "failed_check": _failed_check_of(r),
            "actual_head": (getattr(r, "actual", "") or "")[:220],
        }
        for r in results
        if r.status is CaseStatus.FAIL
    ]
    errors = [
        {"id": r.case_id, "detail": r.detail}
        for r in results
        if r.status is CaseStatus.ERROR
    ]
    passed = sum(1 for r in results if r.status is CaseStatus.PASS)
    total = len(results)
    return {
        "aggregates": {
            "total": total,
            "passed": passed,
            "failed": len(failures),
            "errors": len(errors),
            "pass_rate": round(passed / total, 4) if total else 0.0,
        },
        "failures": failures,
        "errors": errors,
        "cases": [
            {
                "id": r.case_id,
                "status": r.status.value
                if hasattr(r.status, "value")
                else str(r.status),
                "detail": r.detail,
                "actual": getattr(r, "actual", ""),
            }
            for r in results
        ],
    }


def _failed_check_of(result: Any) -> str | None:
    """Extract the rubric check name from a failure detail line."""
    detail = getattr(result, "detail", "") or ""
    marker = "rubric check '"
    if marker in detail:
        rest = detail.split(marker, 1)[1]
        return rest.split("'", 1)[0]
    return None


def main() -> int:  # noqa: PLR0915 — a probe reads top to bottom
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument(
        "--arms",
        default="D,A,B",
        help="Comma-separated arms to run in order (default D,A,B). Arm B "
        "mutates the pipeline template and always runs last.",
    )
    parser.add_argument(
        "--runtime-label",
        default=None,
        help="Label for the output filename (default: the detected OV version).",
    )
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument(
        "--allow-arm-c",
        action="store_true",
        help="Run the wrapper-side strip fallback if D/A/B all fail.",
    )
    args = parser.parse_args()

    try:
        import openvino as ov
        import openvino_genai as ov_genai
    except ImportError as exc:
        _fail(f"OpenVINO GenAI is not importable here: {exc}")
        return 2

    from shared.perf_env_capture import capture_box_state

    model_dir = Path(args.model_dir)
    if not (model_dir / "openvino_language_model.xml").exists():
        _fail(f"no openvino_language_model.xml under {model_dir}")
        return 2

    ov_version = ov.__version__
    genai_version = ov_genai.__version__
    label = args.runtime_label or ov_version.split("-")[0]

    print("=" * 72)
    print("  S0c — thinking control on the Qwen3.6-35B-A3B (#1611)")
    print(f"  OpenVINO   : {ov_version}")
    print(f"  GenAI      : {genai_version}")
    print(f"  Model      : {model_dir}")
    print("=" * 72)

    box_at_start = capture_box_state()
    budget = box_at_start.get("gpu_budget", {})
    print(f"  GPU budget : {budget}")
    print(f"  Uptime     : {box_at_start.get('machine_uptime_s')} s")

    # --- the witness check, before anything is scored -------------------
    tokenizer = ov_genai.Tokenizer(str(model_dir))
    mapping = verify_think_token_mapping(tokenizer)
    print(f"  think-token mapping verified: {mapping['usable']}  {mapping}")

    from evals.suites.answer_quality import _default_system_prompt, run_suite

    system_prompt = _default_system_prompt()

    print(f"\nLoading VLMPipeline (one load, reused by every arm) ...")
    t_load = time.perf_counter()
    try:
        pipe = ov_genai.VLMPipeline(str(model_dir), "GPU")
    except Exception as exc:  # noqa: BLE001
        _fail(f"VLMPipeline failed to load: {exc}")
        return 3
    load_seconds = time.perf_counter() - t_load
    print(f"Loaded in {load_seconds:.1f}s")

    original_template = (model_dir / "chat_template.jinja").read_text(encoding="utf-8")

    arm_specs = {
        "D": "production recipe: wrap_chatml + empty think block, apply_chat_template=False",
        "A": 'ChatHistory.set_extra_context({"enable_thinking": False})',
        "B": "set_chat_template with the thinking condition inverted (no-think default)",
        "C": "FALLBACK, measured not adopted: wrapper-side strip of the reasoning block",
    }

    requested = [a.strip().upper() for a in args.arms.split(",") if a.strip()]
    # B mutates the pipeline; it must not run before D or A.
    requested.sort(key=lambda a: {"D": 0, "A": 1, "B": 2, "C": 3}.get(a, 9))

    results: list[ArmResult] = []
    gates: dict[str, Any] = {}

    for arm in requested:
        if arm == "C":
            continue  # only reached via the fallback block below
        print(f"\n{'=' * 72}\n  ARM {arm} — {arm_specs.get(arm, '?')}\n{'=' * 72}")
        result = ArmResult(arm, arm_specs.get(arm, ""))

        if arm == "B":
            patched = original_template.replace(
                TEMPLATE_COND, TEMPLATE_COND_NOTHINK_DEFAULT
            )
            if patched == original_template:
                result.error = (
                    "template patch did not apply — the thinking condition was not "
                    "found verbatim; arm B not measured"
                )
                print(f"  SKIPPED: {result.error}")
                results.append(result)
                continue
            # FAIL-SOFT PER ARM. The first run of this probe lost arms D and A
            # entirely because this call raised ("Chat mode is not supported" —
            # set_chat_template is unavailable on the VLM continuous-batching
            # adapter) and took the process down before any evidence was
            # written. An instrument must not discard the measurements it has
            # already taken because a later arm is unsupported.
            try:
                pipe.set_chat_template(patched)
                print("  pipeline chat template replaced (no-think default)")
            except Exception as exc:  # noqa: BLE001
                result.error = (
                    f"set_chat_template unavailable on this pipeline: "
                    f"{type(exc).__name__}: {exc}"
                )
                print(f"  ARM UNAVAILABLE: {result.error}")
                results.append(result)
                continue

        gen = build_arm_generator(
            pipe,
            tokenizer,
            ov_genai,
            arm,
            system_prompt=system_prompt,
            max_new_tokens=args.max_new_tokens,
            result=result,
        )

        t0 = time.perf_counter()
        try:
            report = run_suite(include_hardware=True, hardware_generator=gen)
            result.suite = summarize_report(report)
        except Exception as exc:  # noqa: BLE001
            result.error = f"{type(exc).__name__}: {exc}"
            print(f"  ARM FAILED: {result.error}")
        result.wall_seconds = time.perf_counter() - t0

        if result.prompt_info:
            print(f"  rendered prompt: {result.prompt_info}")
        if result.suite:
            agg = result.suite["aggregates"]
            print(
                f"  suite: {agg['passed']}/{agg['total']} passed "
                f"({agg['failed']} failed, {agg['errors']} errors) "
                f"in {result.wall_seconds:.0f}s"
            )
        gates[arm] = score_arm(result, mapping["usable"])
        print(f"  GATE: {'PASS' if gates[arm]['ARM_PASSES'] else 'FAIL'}")
        for k in (
            "no_think_tag_failures",
            "start_anchor_cases",
            "prompt_well_formed",
            "first_token_note",
        ):
            print(f"    {k}: {gates[arm].get(k)}")
        results.append(result)

    any_pass = any(g.get("ARM_PASSES") for g in gates.values())

    if not any_pass and args.allow_arm_c:
        print(f"\n{'=' * 72}\n  ARM C (fallback) — {arm_specs['C']}\n{'=' * 72}")
        result = ArmResult("C", arm_specs["C"])
        gen = build_arm_generator(
            pipe,
            tokenizer,
            ov_genai,
            "C",
            system_prompt=system_prompt,
            max_new_tokens=args.max_new_tokens,
            result=result,
            strip_thinking=True,
        )
        t0 = time.perf_counter()
        try:
            report = run_suite(include_hardware=True, hardware_generator=gen)
            result.suite = summarize_report(report)
        except Exception as exc:  # noqa: BLE001
            result.error = f"{type(exc).__name__}: {exc}"
        result.wall_seconds = time.perf_counter() - t0
        gates["C"] = score_arm(result, mapping["usable"])
        results.append(result)

    box_at_end = capture_box_state()
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"probe_35b_thinking_control_{label}_{stamp}.json"

    summary = {
        "probe": "35b_thinking_control",
        "ticket": "#1611 S0c",
        "model": model_dir.name,
        "model_dir": str(model_dir),
        "device": "GPU",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "openvino_version": ov_version,
        "openvino_genai_version": genai_version,
        "runtime_label": label,
        "load_seconds": round(load_seconds, 1),
        "max_new_tokens": args.max_new_tokens,
        "think_token_mapping": mapping,
        "environment": {
            "box_state_at_start": box_at_start,
            "box_state_at_end": box_at_end,
        },
        "july_baseline": {
            "source": "docs/performance/eval_35b-a3b_answer_quality_ov_2026-07-17.json",
            "passed": 22,
            "total": 40,
            "no_think_tag_failures": 10,
            "start_anchor_failures": list(START_ANCHOR_CASES),
            "note": (
                "The July run left apply_chat_template at its default True with no "
                "enable_thinking, so the template appended a bare '<think>\\n' and "
                "the run asked the model to think on every case."
            ),
        },
        "gate_denominator_correction": (
            "The written gate said 'first token != 248068 in >= 39/40'. The golden "
            "file holds 40 cases but only 19 are model mode; 21 are offline "
            "fixtures that never reach the model. The gate here keeps the "
            "one-case tolerance on the real denominator: >= 18 of 19."
        ),
        "arms": [r.to_dict() for r in results],
        "gates": gates,
        "verdict": {
            "any_arm_passes": any(g.get("ARM_PASSES") for g in gates.values()),
            "passing_arms": [a for a, g in gates.items() if g.get("ARM_PASSES")],
        },
        "not_measured": [
            "Throughput/TTFT under each arm (S0a and S0b own the speed numbers).",
            "Whether a no-think prompt changes answer quality on the cases that "
            "fail for non-thinking reasons (injection, system-prompt leak, arithmetic).",
            "Any runtime other than the one this process ran under.",
            "Multi-turn behaviour: every case here is a single turn.",
        ],
    }
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'=' * 72}")
    print(f"  VERDICT: passing arms = {summary['verdict']['passing_arms'] or 'NONE'}")
    print(f"  results: {out_path}")
    print(f"{'=' * 72}")
    return 0 if summary["verdict"]["any_arm_passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
