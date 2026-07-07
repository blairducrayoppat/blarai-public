@andrey-golubev — checking in on the IR-dumping question from my April 17 reply: which env vars or compiler flags let me capture the IR after each pass in the NPU pipeline, so I can identify where the zero-dim shape is introduced? I'd like to follow your direction toward a root-cause fix, but I haven't been able to find the right knob from outside the project. Happy to wait if other items have priority — just want to make sure you have what you need from me to keep this moving.

@DariaMityagina — also flagging: I added the LIT test you requested at `tests/lit/NPU/dialect/IE/passes/unroll_fully_connected_zero_dim_guard.mlir` in commit `c5f9266`. Let me know if it's structured the way you'd want, or if it needs adjustments.

---

**AI Assistance:** AI assistance used: yes — Claude helped draft this follow-up comment. No new technical investigation was performed for this comment; all referenced material (commit SHA, test path, IR-dumping question) is from the April 17 conversation already on this PR.
