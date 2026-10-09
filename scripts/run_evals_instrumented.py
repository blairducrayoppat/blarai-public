"""Run ``python -m evals.run`` from THIS checkout with progress + witness output.

Why this exists (#1663): the hardware eval arms must be launched detached and
watched by content, not by process presence. This launcher adds, without
touching the harness:

* ``--status-file``  one line per scored case, appended as the case lands, so a
  Monitor can tell "running" from "hung" by new lines instead of a live PID.
* ``--models-root``  the directory production's relative model paths resolve
  against (the draft model path is cwd-relative). A git worktree has only the
  tracked stubs, so the real ``models/`` directory is named here and the
  process changes into it. Python imports still resolve from THIS checkout.
* ``--engine-summary``  at exit, dumps the CB engine's witness (accepted draft
  tokens, first-chunk ``<think>`` count) next to the report.
* ``--pin-marker``  replaces the per-load random datamark with a fixed token, so
  a repeat sends the model the SAME prompt. Production's marker is random on
  purpose; pinning is a measurement control, never a production change.
* ``--perturb V0|V1|V2|V3``  meaning-preserving prompt perturbations (V0 as-is, V1 one
  trailing space, V2 double space after full stops, V3 one space before the final
  punctuation mark - the only one a whitespace-trimming chat template cannot
  erase), applied to each golden
  case's ``prompt`` and ``prior_turns`` text before the suite sees it.
* ``--io-log``  one JSONL row per model call: SHA-256 of the prompt actually sent
  and of the text returned. This is how "the inputs were identical" is MEASURED
  rather than assumed (the stop condition "the control disagrees with itself"
  only means something when the inputs are proven equal).

Every other argument is forwarded to ``evals.run`` unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT))


def _install_progress(status_file: Path, tag: str) -> None:
    from evals import types as eval_types

    status_file.parent.mkdir(parents=True, exist_ok=True)

    class _ProgressList(list):  # noqa: D401 — appends a status line per result
        def __init__(self, suite: str) -> None:
            super().__init__()
            self._suite = suite

        def append(self, item) -> None:  # type: ignore[override]
            super().append(item)
            line = {
                "t": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "tag": tag,
                "suite": self._suite,
                "case": getattr(item, "case_id", "?"),
                "status": getattr(getattr(item, "status", None), "value", "?"),
                "n": len(self),
            }
            with open(status_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")

    original_init = eval_types.SuiteReport.__init__

    def _init(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        original_init(self, *args, **kwargs)
        existing = list(self.results)
        self.results = _ProgressList(self.suite)
        for item in existing:
            self.results.append(item)

    # A dataclass only calls __post_init__ when it existed at decoration time,
    # so the constructor itself is wrapped.
    eval_types.SuiteReport.__init__ = _init  # type: ignore[method-assign]


PINNED_MARKER = "<|DOC-0badc0de|>"


def _pin_marker() -> None:
    from services.assistant_orchestrator.src import context_manager

    context_manager._generate_data_marker = lambda: PINNED_MARKER  # type: ignore[assignment]


def _perturb_text(text: str, variant: str) -> str:
    if variant == "V1":
        return text + " "
    if variant == "V2":
        return text.replace(". ", ".  ")
    if variant == "V3":
        # one space before the terminal punctuation mark: meaning-preserving, and
        # (unlike V1) not erased by a chat template that trims message bodies
        stripped = text.rstrip()
        if stripped and stripped[-1] in ".?!" and len(stripped) > 1:
            return stripped[:-1] + " " + stripped[-1] + text[len(stripped):]
        return text
    return text


def _install_perturbation(variant: str) -> None:
    """Wrap ``evals.loader.load_golden`` (suites import it lazily, so this lands first)."""
    from evals import loader

    original = loader.load_golden

    def perturbed(path):  # type: ignore[no-untyped-def]
        cases = original(path)
        if variant == "V0":
            return cases
        for case in cases:
            if isinstance(case.get("prompt"), str):
                case["prompt"] = _perturb_text(case["prompt"], variant)
            turns = case.get("prior_turns")
            if isinstance(turns, list):
                for turn in turns:
                    if isinstance(turn, dict) and isinstance(turn.get("content"), str):
                        turn["content"] = _perturb_text(turn["content"], variant)
        return cases

    loader.load_golden = perturbed  # type: ignore[assignment]


def _install_io_log(path: Path, tag: str) -> None:
    """Log SHA-256 of every prompt sent and text returned, for AO and PA calls."""
    import hashlib

    def sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]

    def write(row: dict) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + chr(10))

    from services.assistant_orchestrator.src.gpu_inference import OrchestratorGPUInference
    from services.policy_agent.src.gpu_inference import (
        CARPromptFormatter,
        ClassificationParser,
        PolicyGPUInference,
    )

    # The Policy Agent result carries the parsed label only; the raw text the model
    # emitted is the input of ClassificationParser.parse, so it is captured there.
    last_pa_text: list[str] = [""]
    orig_parse = ClassificationParser.parse.__func__  # type: ignore[attr-defined]

    def parse(cls, text):  # type: ignore[no-untyped-def]
        last_pa_text[0] = text if isinstance(text, str) else ""
        return orig_parse(cls, text)

    ClassificationParser.parse = classmethod(parse)  # type: ignore[method-assign]

    orig_ao = OrchestratorGPUInference._generate_from_prompt

    def ao(self, prompt, *a, **kw):  # type: ignore[no-untyped-def]
        result = orig_ao(self, prompt, *a, **kw)
        text = getattr(result, "text", "") or ""
        write({"tag": tag, "kind": "ao", "prompt_sha": sha(prompt), "prompt_len": len(prompt),
               "out_sha": sha(text), "out_len": len(text),
               # Tool-call FORMAT witnesses: production parses JSON <tool_call> only;
               # Qwen3.5's template trains XML <function=...> calls (gate-review D9).
               "xml_tool_call": "<function=" in text,
               "json_tool_call": "<tool_call>" in text and "<function=" not in text,
               "out_text": text[:4000]})
        return result

    OrchestratorGPUInference._generate_from_prompt = ao  # type: ignore[method-assign]

    orig_pa = PolicyGPUInference.classify_car

    def pa(self, car, *a, **kw):  # type: ignore[no-untyped-def]
        last_pa_text[0] = ""
        result = orig_pa(self, car, *a, **kw)
        try:
            prompt = CARPromptFormatter.build_prompt(car)
        except Exception:  # noqa: BLE001 - the row just lacks a prompt hash
            prompt = ""
        row = {"tag": tag, "kind": "pa", "prompt_sha": sha(prompt), "prompt_len": len(prompt),
               "out_sha": sha(f"{result.label}|{result.confidence}|{result.error}"), "label": result.label}
        if os.environ.get("BLARAI_EVAL_PA_RAW") == "1":  # opt-in: raw classifier text for diagnosis
            row.update(confidence=result.confidence, error=result.error, out_text=last_pa_text[0][:400])
        write(row)
        return result

    PolicyGPUInference.classify_car = pa  # type: ignore[method-assign]


def _absolutize_report_path(argv: list[str]) -> list[str]:
    """Make ``--report`` absolute, since the process changes directory."""
    out = list(argv)
    for i, tok in enumerate(out):
        if tok == "--report" and i + 1 < len(out):
            out[i + 1] = str(Path(out[i + 1]).resolve())
        elif tok.startswith("--report="):
            out[i] = "--report=" + str(Path(tok.split("=", 1)[1]).resolve())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    ap.add_argument("--status-file", type=Path, required=True)
    ap.add_argument("--models-root", type=Path, required=True)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--engine-summary", type=Path, default=None)
    ap.add_argument("--pin-marker", action="store_true")
    ap.add_argument("--perturb", choices=("V0", "V1", "V2", "V3"), default=None)
    ap.add_argument("--io-log", type=Path, default=None)
    ours, rest = ap.parse_known_args()
    # Absolute BEFORE the chdir below: a relative path would otherwise land in
    # the models-root checkout, which is some other session's working tree.
    ours.status_file = ours.status_file.resolve()
    ours.models_root = ours.models_root.resolve()
    if ours.engine_summary is not None:
        ours.engine_summary = ours.engine_summary.resolve()
    if ours.io_log is not None:
        ours.io_log = ours.io_log.resolve()
    rest = _absolutize_report_path(rest)
    stats_path = os.environ.get("BLARAI_EVAL_CB_STATS")
    if stats_path:
        os.environ["BLARAI_EVAL_CB_STATS"] = str(Path(stats_path).resolve())

    os.chdir(ours.models_root)
    _install_progress(ours.status_file, ours.tag)
    if ours.pin_marker:
        _pin_marker()
    if ours.perturb:
        _install_perturbation(ours.perturb)
    if ours.io_log is not None:
        _install_io_log(ours.io_log, ours.tag)

    from evals.run import main as eval_main

    code = eval_main(rest)

    if ours.engine_summary is not None:
        from evals.cb_pipeline import assert_mtp_engaged, registered_pipelines

        summaries = []
        for pipe in registered_pipelines():
            try:
                summaries.append(assert_mtp_engaged(pipe))
            except Exception as exc:  # noqa: BLE001 — recorded, exit code reflects it
                summaries.append({"engine": pipe.engine, "witness_error": str(exc)})
                # exit 1 means "differs from the 14B baselines" (data); a missing
                # MTP witness is a different thing and must not hide behind it
                code = 3
        ours.engine_summary.write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
    with open(ours.status_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tag": ours.tag, "job_done": True, "exit": code}) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
