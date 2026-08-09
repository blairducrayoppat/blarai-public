# Disposition — #1165 M1 interview voice, independent pre-merge review (2026-07-29)

Review: independent author≠verifier review over commits `3e417b96`..`9963fea3` on
`feat/1165-m1-interview-voice`, verdict **NEEDS-FIXES** (1 HIGH / 2 MED / 1 LOW). The
reviewer proved F2 by execution (voice ON + quick park + whole-reply "I don't know" took
the decide-defaults turn) and caught F1 through the #1158 parity gate the builder's
scoped runs had not reached. F4 is the builder's argued deviation, adjudicated as
standing and recorded as the deferral it is. Fix round authored by the builder; the
fix commits were independently fix-verified by execution by the same reviewer —
**APPROVE pinned at `8d787b34`** (never self-certified).

Measured counts (builder, at the fix-round tip, per file): test_interview_voice.py
11 passed, test_interview_voice_coordinator.py 9 passed, test_intake_interview.py
16 passed, test_intake_interview_coordinator.py 21 passed — 0 failed / 0 skipped
throughout; scoped seven-file aggregate (those four + test_dispatch_coordinator.py +
test_dispatch_harness.py + test_plan_handler.py) 308 passed / 0 failed / 0 skipped.
Independent check (reviewer, at `8d787b34`, their eight-file selection): 589 passed /
0 failed / 0 skipped. The builder's original report cited "108/0/0 on five files" —
a REPORTING ERROR: the figure carried no tree tip or file-set pin and did not
reproduce for the reviewer; the figures above are the measured record.

```disposition
F1 the #1158 harness parity gate failed on the branch - the launcher threaded the voice kwarg but neither harness TransportGateway construction did, so a harness or console drive would exercise a narrower gateway than production | FIXED | 716f3e88 - for_live gains the kwarg threaded into BOTH constructions; the key joins the strict ceremony-flag set in load_harness_config (now four flags, is-True per #1042); console_gateway_kwargs + the posture light gain it; the ceremony-flag and console-mirror locks extended; parity gate green (79 passed)
F2 the I-don't-know hatch engaged corridor-wide under the voice flag - a quick-path park answered "I don't know" took the decide-defaults turn, contradicting the design SS0 byte-for-byte promise the LA approved and the branch's own default.toml and entrypoint intake-only comments | FIXED | ea9b5b9c - the answer path passes dont_know=voice AND pending_req.intake; discriminating locks in both directions (quick park + voice ON stays a substantive verbatim answer byte-identical to a keyword-less coordinator; intake park + voice ON routes to decide-defaults with assumed=True)
F3 the research template SSOT was cited by the design doc, default.toml's flag comment, and clarify.py docstrings but existed only as an untracked file in the main checkout | FIXED | 8d787b34 - docs/research/novice-interview-template-research-2026-07-29.md landed on the branch byte-identical to the source (SHA256 901d831103a70559beb4ab7608bac6d0f02bdbeb64fd8002bfb604f4ae331916 on both copies)
F4 intake_template_for ships without the proposals keyword the design SS2 signature sketch names | DEFERRED | #1165 - blocked-by: #1165 M3 slice (the `proposals` keyword lands WITH its propose-and-veto behavior, never as a silent no-op stub in M1) - the reviewer accepted the argument; the deferral makes it observable
```

## Notes

- F3's byte-identity was verified by SHA256 after the commit (the commit message names
  `fc /b`, which errored on switch mangling and verified nothing — the hash above is
  the real evidence; source file in the main checkout untouched).
- F1's fix deliberately includes `tools/dispatch_console.py`: the console rides
  `for_live` and mirrors the shipped posture, so omitting it would re-create the same
  narrower-gateway class one caller over. `battery.py` and `__main__.py` call
  `for_live` without the new kwarg and stay byte-identical via its False default.
