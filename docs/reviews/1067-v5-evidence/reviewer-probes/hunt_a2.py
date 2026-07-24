"""HUNT A follow-up: the word-order A/B on the builder's OWN veto lexicon."""
from __future__ import annotations

import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/a3ea2b99-dc32-471f-987a-cb94d1f4e064/scratchpad")
from probe_harness import run, GUARD_V4, TRUTH_V4, pg_v4  # noqa: E402

ADJ = ["false", "untrue", "incorrect", "inconceivable", "unthinkable",
       "impossible", "implausible", "improbable", "doubtful", "unlikely",
       "absurd", "wrong"]

print("=== word-order A/B on every adjective in _NEGATION_MARKER_RE ===")
print(f"{'adj':16} {'PRE-posed (in corpus)':24} {'POST-posed (not tested)'}")
for a in ADJ:
    pre = f"INCOMPLETE: it is {a} that the run did not complete successfully."
    post = f"INCOMPLETE: the claim that the run did not complete successfully is {a}."
    _, _, va_pre, _ = run(pre)
    _, _, va_post, _ = run(post)
    print(f"{a:16} {'ACCEPTED <<<' if va_pre else 'refused':24} "
          f"{'ACCEPTED  <<< FALSE ACCEPTANCE' if va_post else 'refused'}")

print("\n=== deny/denies/denied: same walk-around ===")
for form in ("denies", "denied", "deny"):
    pre = f"INCOMPLETE: nobody {form} that the run did not complete successfully."
    post = f"INCOMPLETE: the claim that the run did not complete successfully is {form} by the board."
    _, _, vp, _ = run(pre)
    _, _, vq, _ = run(post)
    print(f"{form:10} pre={'ACC' if vp else 'REJ'}  post={'ACC' if vq else 'REJ'}")

print("\n=== identity check on _screen: is `claims is _SUCCESS_CLAIMS` reachable-safe? ===")
import inspect  # noqa: E402
src = inspect.getsource(pg_v4.ProseGuard._screen)
print("claims assigned from module constants only:",
      "claims = _SUCCESS_CLAIMS" in src and "claims = _FAILURE_CLAIMS" in src)

print("\n=== validate_annotation: does the carve-out reach the second door? ===")
for t in ("the task did not complete successfully",
          "the redispatch could not complete successfully",
          "the overall run did not complete successfully"):
    d4 = GUARD_V4.validate_annotation(t)
    print(f"  annotation v4={'ACC' if d4.accepted else 'REJ'}  ({d4.action})  {t!r}")

print("\n=== marker-count swallow check: can adding a negation REDUCE the count? ===")
probes = [
    ("cannot", "not"), ("didn't", "not"), ("unable to", "not able to"),
    ("no longer", "not"), ("failed to", "fail to"),
]
for a, b in probes:
    print(f"  {a!r} -> {len(pg_v4._NEGATION_MARKER_RE.findall(a))} markers; "
          f"{b!r} -> {len(pg_v4._NEGATION_MARKER_RE.findall(b))} markers")
