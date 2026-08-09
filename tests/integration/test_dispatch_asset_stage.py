"""#1125 / #1127 — the dispatch ASSET stage: how many images, and who holds the RAM.

Both defects were found by the operator on 2026-07-27, in the same run, minutes apart.

#1125: his goal named FOUR images. The stage wrote three and said so (`3/3 written`),
because `DEFAULT_MAX_ASSETS` was 3 — while the plan card he had just approved carried an
AUTOMATIC check reading "rotates through all four generated images". The cap's own comment
justified 3 as keeping generation "under the dispatch interception timeout", a timeout
#1122 had raised from 175 s to 540 s earlier the same day. The number outlived its reason.

#1127: seven seconds after writing those images the swap driver's headroom gate measured
20.0 GiB against a 20 GiB requirement and ABORTED the whole dispatch — while roughly
2.5 GiB of the shortfall was the image pipeline holding memory it was about to release on
a 60-second idle timer. Generating images made the very next swap MORE likely to fail,
which penalises exactly the image-heavy projects that need the coder.
"""

from __future__ import annotations

import inspect

from shared.fleet import acceptance as acc


def test_asset_cap_is_measured_against_the_current_timeout_not_the_retired_one():
    """#1125 — 8 at ~43 s/image is ~344 s inside the 540 s budget.

    Pinned as a RELATIONSHIP, not a bare value: the cap exists to fit inside the dispatch
    interception fail-safe, and that fail-safe has already moved once (175 -> 540) without
    the cap following. If someone shortens the budget again, this fails instead of quietly
    re-creating the same mismatch.
    """
    from services.ui_backend.src.dispatcher import _DISPATCH_STREAM_FAILSAFE_S

    measured_seconds_per_image = 43.0   # Arc 140V, 2026-07-27, incl. pipeline load
    #: Headroom the same turn needs for the plan + project creation that share the budget.
    reserved_for_the_rest_of_the_turn = 150.0

    worst_case = acc.DEFAULT_MAX_ASSETS * measured_seconds_per_image
    assert worst_case + reserved_for_the_rest_of_the_turn <= _DISPATCH_STREAM_FAILSAFE_S, (
        f"{acc.DEFAULT_MAX_ASSETS} images x {measured_seconds_per_image}s = {worst_case}s "
        f"does not fit the {_DISPATCH_STREAM_FAILSAFE_S}s dispatch budget with room for the "
        "plan and project creation — lower the cap or raise the budget, deliberately."
    )


def test_asset_cap_is_still_bounded():
    """The LA asked to "remove the image cap"; the shipped answer is a RAISE, not removal.

    An unbounded cap lets a goal like "an image for every chapter" commit the GPU for as
    long as the model felt like enumerating, inside a turn with a hard deadline — and the
    failure is a timeout mid-generation, not a clean refusal. Recorded here so a future
    reader does not "finish the job" by removing it.
    """
    assert isinstance(acc.DEFAULT_MAX_ASSETS, int)
    assert 4 <= acc.DEFAULT_MAX_ASSETS <= 12


def test_the_cap_reaches_the_grammar_schema():
    """Reachability: a constant no emission path reads is worth nothing."""
    schema = acc.asset_specs_emission_json_schema()
    assert schema["maxItems"] == acc.DEFAULT_MAX_ASSETS


def test_the_asset_stage_releases_the_image_pipeline_before_the_swap():
    """#1127 — THE REGRESSION LOCK, read from source.

    Behavioural coverage would need a real diffusion pipeline and a real swap gate, which
    the standing gate cannot run. What CAN be locked deterministically is that the release
    call is present in the stage that precedes `step_aside()` — the defect was never a
    wrong value, it was a missing call, and the pipeline's own idle timer is not a
    substitute because the next step outruns it.
    """
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )

    source = inspect.getsource(
        AssistantOrchestratorService._maybe_generate_dispatch_assets
    )
    assert "image_gen.unload()" in source, (
        "the dispatch asset stage must release the image pipeline before the swap "
        "(#1127) — without it the headroom gate measures through memory the pipeline "
        "is about to free, and aborts the dispatch that generated the images"
    )
    # ...and it must run BEFORE the availability is reported, so the logged figure is the
    # reclaimed one rather than the number the gate will wrongly act on.
    assert source.index("image_gen.unload()") < source.index("avail_after"), (
        "release the pipeline BEFORE measuring/reporting available RAM"
    )
