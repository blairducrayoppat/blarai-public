"""Confirmations: secondary #5, the acknowledged new suppression, and the
docstring's stated safety property."""
from __future__ import annotations

import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/a3ea2b99-dc32-471f-987a-cb94d1f4e064/scratchpad")
from probe_harness import run, pg_v4, pg_main  # noqa: E402

print("=== SECONDARY #5: 'The run successfully completed' (verb-AFTER-adverb) ===")
for t in ("The run successfully completed.",
          "The run successfully finished and merged.",
          "The build successfully completed all six tasks.",
          "The suite successfully ran.",
          "Everything successfully completed."):
    ma, mact, va, vact = run(t)
    print(f"  main={'ACC' if ma else 'REJ'} ({mact:38}) v4={'ACC' if va else 'REJ'} ({vact:38}) {t!r}")

print("\n=== builder's own acknowledged new suppression (c.2472 item 3) ===")
for t in ("The run successfully merged three tasks.",
          "The run successfully parked at implement-quiz-logic."):
    ma, _, va, _ = run(t)
    print(f"  main={'ACC' if ma else 'REJ'}  v4={'ACC' if va else 'REJ'}   {t!r}")

print("\n=== the docstring's SAFETY PROPERTY, tested directly ===")
print("Claim: 'ADDING negation to any text can only move it toward refusal'")
print("       'a miscount is therefore a false refusal ... never a false acceptance'\n")
pairs = [
    ("it is false that the run did not complete successfully.",
     "the claim that the run did not complete successfully is false."),
    ("it is untrue that the run did not complete successfully.",
     "the report that the run did not complete successfully is untrue."),
]
for a, b in pairs:
    _, _, va, _ = run(a)
    _, _, vb, _ = run(b)
    na = len(pg_v4._NEGATION_MARKER_RE.findall(a))
    nb = len(pg_v4._NEGATION_MARKER_RE.findall(b))
    print(f"  IN CORPUS  markers={na} v4={'ACCEPTED' if va else 'refused '}  {a!r}")
    print(f"  WORD-ORDER markers={nb} v4={'ACCEPTED' if vb else 'refused '}  {b!r}")
    print("    -> same words, same semantics, count UNDERCOUNTS by one -> ACCEPTANCE\n")

print("=== is the hole reachable through the production entry point? ===")
print("  (validate_run_summary is the run-summary door; see caller grep)")
truth = pg_v4.RunTruth("20260719-002208-bd", oracle_passed=False, merged=True, parked=False)
g = pg_v4.ProseGuard()          # production construction: defaults, no toggles
text = ("INCOMPLETE: The earlier note that the run did not complete successfully "
        "was incorrect; all six tasks merged and the exam is green.")
d = g.validate_run_summary(truth, text)
print(f"  verdict={truth.verdict()}  accepted={d.accepted}  action={d.action!r}")
print(f"  text={text!r}")
