"""pytest plugin: report the first test after which guarded_fetch._adjudicator is left registered."""
import pytest

_seen = {"first": None}


def pytest_runtest_logfinish(nodeid, location):
    try:
        from shared.security import guarded_fetch
    except Exception:
        return
    if guarded_fetch._adjudicator is not None and _seen["first"] is None:
        _seen["first"] = nodeid
        print("\nPOLLUTER-FIRST: " + nodeid, flush=True)


def pytest_sessionfinish(session, exitstatus):
    print("POLLUTER-SUMMARY: " + str(_seen["first"]), flush=True)
