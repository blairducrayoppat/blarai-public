"""A2: hunt for UNBOUND variable positions (the design claims there is only one,
bound to task names)."""
from d import sweep, both

# The counted form has TWO \d+ positions bound to NOTHING but num<den.
sweep("F1: counted-pass numbers are an unbound slot", [
    "only 8 of 9 tests passed.",
    "only 8 of 9 tests passed",
    "only 99 of 100 acceptance tests passed.",
    "only 999 out of 1000 unit tests passed.",
    "only 8 out of 9 tests passed and the run did not complete successfully.",
    "The run did not complete successfully, but only 8 of 9 acceptance tests passed.",
    "only 1 of 2 tests passed.",
    "only 8 of 9 tests pass.",
])

# Sanity: the guard's own fraction rule
sweep("F1b: improper fractions must still refuse", [
    "only 9 of 9 tests passed.",
    "only 10 of 9 tests passed.",
    "only 0 of 0 tests passed.",
])

# unicode digits / leading zeros
sweep("F1c: numeric edge forms", [
    "only ٨ of ٩ tests passed.",     # arabic-indic 8 of 9
    "only 08 of 9 tests passed.",
    "only 8 of 09 tests passed.",
])

# merge-status: names bound, RESULT unbound
sweep("F2: merge assertions are unchecked against results", [
    "The run did not complete successfully and bill-splitter and acceptance-tests were merged.",
    "The run did not complete successfully, yet the bill-splitter and acceptance-tests components have been merged.",
    "no tests passed but bill-splitter and acceptance-tests were merged.",
])
