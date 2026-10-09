"""Single registry of the Qwen3.5 sizes the Phase 1 harness measures (#1663).

Every script that names an arm, a model directory, a campaign model or a dataset
directory resolves it HERE, so a size can never be paired with another size's
directory or label. Pure: imports no openvino and touches no file.

Arm name = ``f"{size}-{variant}"`` with ``size`` a key of ``SIZES`` and ``variant``
one of ``VARIANTS``; the reference arm ``14b-ship`` has no size.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: size -> default model directory (override per size with ``--model-<size>``).
SIZES: dict[str, Path] = {
    "4b": Path("B:/models/Qwen3.5-4B-int8-ov"),
    "9b": Path("B:/models/Qwen3.5-9B-int8-ov"),
}
VARIANTS = ("mtp-off", "mtp-on", "prefix-cache")
VARIANT_ENGINE = {"mtp-off": "cb-mtp-off", "mtp-on": "cb-mtp-on", "prefix-cache": "cb-prefix-cache"}
ARM_14B = "14b-ship"
RUNTIME_SHIP = "2026.2.1"
RUNTIME_NEW = "2026.4"
#: The 14B as it ships, on the shipped runtime: the denominator every size is read against.
REF_14B = f"{ARM_14B}@{RUNTIME_SHIP}"


def arm_name(size: str, variant: str) -> str:
    if size not in SIZES or variant not in VARIANTS:
        raise ValueError(f"unknown arm size/variant: {size!r}/{variant!r}")
    return f"{size}-{variant}"


def cb_arms(size: str) -> tuple[str, ...]:
    """The three continuous-batching arms of one size, in canonical order."""
    return tuple(arm_name(size, v) for v in VARIANTS)


def parse_arm(name: str) -> tuple[str, str] | None:
    """``(size, variant)`` for a CB arm, ``None`` for anything else (incl. ``14b-ship``)."""
    size, _, variant = name.partition("-")
    if size in SIZES and variant in VARIANTS:
        return size, variant
    return None


def all_arms(sizes: tuple[str, ...] | list[str] = ("4b",)) -> tuple[str, ...]:
    out: list[str] = []
    for s in sizes:
        out.extend(cb_arms(s))
    return tuple(out) + (ARM_14B,)


def size_of(name: str) -> str | None:
    """Size token of an arm or an ``@runtime``-labelled arm; ``None`` for the 14B."""
    parsed = parse_arm(name.split("@")[0])
    return parsed[0] if parsed else None


def engine_for(name: str) -> str:
    parsed = parse_arm(name)
    if parsed is None:
        raise KeyError(f"not a continuous-batching arm: {name!r}")
    return VARIANT_ENGINE[parsed[1]]


def model_dir_for(name: str, args: Any) -> Path:
    """The directory ``args.model_<size>`` of the arm's OWN size; never another size's."""
    parsed = parse_arm(name)
    if parsed is None:
        raise KeyError(f"not a continuous-batching arm: {name!r}")
    return Path(getattr(args, f"model_{parsed[0]}"))


def add_model_args(ap: Any) -> None:
    """``--model-4b`` / ``--model-9b`` (one flag per registered size)."""
    for size, default in SIZES.items():
        ap.add_argument(f"--model-{size}", default=str(default))


def resolve_model_args(args: Any) -> None:
    """Absolute-ise every ``model_<size>`` path (before any chdir)."""
    for size in SIZES:
        setattr(args, f"model_{size}", str(Path(getattr(args, f"model_{size}")).resolve()))


def sizes_in(arms: Any) -> list[str]:
    """Registered sizes that appear in ``arms`` (arm names, optionally ``@runtime``-labelled),
    in registry order."""
    present = {size_of(a) for a in arms}
    return [s for s in SIZES if s in present]


def ratio_pairs(sizes: list[str]) -> list[tuple[str, str]]:
    """Ordered (numerator, denominator) arm labels for the speed analysis.

    Per size: on/off, prefix-cache/off, on/prefix-cache, off and on against the shipped
    14B. Then the runtime-confound pair of the 14B (once). Then, for each pair of sizes
    present, the larger over the smaller for mtp-on and mtp-off.
    """
    pairs: list[tuple[str, str]] = []
    for s in sizes:
        on, off, pc = arm_name(s, "mtp-on"), arm_name(s, "mtp-off"), arm_name(s, "prefix-cache")
        pairs += [(on, off), (pc, off), (on, pc), (off, REF_14B), (on, REF_14B)]
    pairs.append((f"{ARM_14B}@{RUNTIME_NEW}", REF_14B))
    order = list(SIZES)
    for i, small in enumerate(order):
        for big in order[i + 1:]:
            if small in sizes and big in sizes:
                for v in ("mtp-on", "mtp-off"):
                    pairs.append((arm_name(big, v), arm_name(small, v)))
    return pairs


# ---------------------------------------------------------------------------
# Quality campaign / dataset naming
# ---------------------------------------------------------------------------

MODEL_14B = "14b"


def quality_models() -> tuple[str, ...]:
    """``--model`` choices of the quality campaign: ``<size>-on``, ``<size>-off``, ``14b``."""
    out: list[str] = []
    for s in SIZES:
        out += [f"{s}-on", f"{s}-off"]
    return tuple(out) + (MODEL_14B,)


def quality_target(model: str) -> tuple[str, str] | None:
    """``(size, engine)`` for a ``<size>-on|off`` model, ``None`` for the 14B."""
    size, _, mode = model.partition("-")
    if size in SIZES and mode in ("on", "off"):
        return size, VARIANT_ENGINE[f"mtp-{mode}"]
    return None


def dataset_quality_dirs() -> dict[str, str]:
    """``_run`` quality directory name -> model name as the dataset labels it."""
    out: dict[str, str] = {}
    for s in SIZES:
        out[f"q{s}_on"] = f"qwen3.5-{s}-int8+mtp"
        out[f"q{s}_off"] = f"qwen3.5-{s}-int8"
    out["q14b"] = "qwen3-14b-int4+draft"
    return out


def dataset_summary_files() -> list[str]:
    """Quality summary files the dataset copies, per size then the 14B."""
    out: list[str] = []
    for s in SIZES:
        out += [f"q{s}_on_summary.json", f"q{s}_off_summary.json"]
    return out + ["q14b_summary.json"]


def dataset_compare_files() -> list[str]:
    """Cross-run comparison files the dataset copies: the 4b names the Phase 1 dataset
    uses, then ``compare_<size>_on_vs_off.json`` / ``compare_<size>_vs_14b.json`` per other size."""
    out = ["compare_on_vs_off.json", "compare_4b_vs_14b.json"]
    for s in SIZES:
        if s != "4b":
            out += [f"compare_{s}_on_vs_off.json", f"compare_{s}_vs_14b.json"]
    return out
