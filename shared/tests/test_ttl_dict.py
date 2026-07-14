"""
TtlDict Tests (#801)
====================
The shared session-lifecycle backstop primitive: a MutableMapping whose
writes are timestamped and whose ``sweep`` evicts entries older than a TTL.
All tests inject a fake clock — no sleeps, fully deterministic.
"""

from __future__ import annotations

from shared.ttl_dict import TtlDict


class _FakeClock:
    """Deterministic monotonic clock for tests."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestMappingProtocol:
    """TtlDict is a drop-in for dict at every MutableMapping call site."""

    def test_set_get_contains_len(self) -> None:
        d: TtlDict[str] = TtlDict(clock=_FakeClock())
        d["a"] = "x"
        assert d["a"] == "x"
        assert "a" in d
        assert len(d) == 1

    def test_get_default_and_pop_default(self) -> None:
        d: TtlDict[str] = TtlDict(clock=_FakeClock())
        assert d.get("missing") is None
        assert d.pop("missing", None) is None
        d["a"] = "x"
        assert d.pop("a", None) == "x"
        assert "a" not in d

    def test_delete_removes_stamp(self) -> None:
        clock = _FakeClock()
        d: TtlDict[str] = TtlDict(clock=clock)
        d["a"] = "x"
        del d["a"]
        assert d.age_s("a") is None

    def test_iteration_and_clear(self) -> None:
        d: TtlDict[int] = TtlDict(clock=_FakeClock())
        d["a"] = 1
        d["b"] = 2
        assert sorted(d) == ["a", "b"]
        d.clear()
        assert len(d) == 0
        assert d.age_s("a") is None

    def test_setdefault_routes_through_setitem(self) -> None:
        clock = _FakeClock()
        d: TtlDict[list[int]] = TtlDict(clock=clock)
        d.setdefault("a", []).append(1)
        assert d["a"] == [1]
        assert d.age_s("a") == 0.0


class TestTtlSemantics:
    """Stamping, aging, expiry, and the disabled-TTL convention."""

    def test_age_tracks_last_write(self) -> None:
        clock = _FakeClock()
        d: TtlDict[str] = TtlDict(clock=clock)
        d["a"] = "x"
        clock.advance(30.0)
        assert d.age_s("a") == 30.0
        d["a"] = "y"  # rewrite restamps
        assert d.age_s("a") == 0.0

    def test_touch_refreshes_stamp(self) -> None:
        clock = _FakeClock()
        d: TtlDict[list[int]] = TtlDict(clock=clock)
        d["a"] = [1]
        clock.advance(100.0)
        d["a"].append(2)  # in-place mutation does NOT restamp...
        assert d.age_s("a") == 100.0
        d.touch("a")  # ...touch does
        assert d.age_s("a") == 0.0

    def test_touch_absent_key_is_noop(self) -> None:
        d: TtlDict[str] = TtlDict(clock=_FakeClock())
        d.touch("missing")  # must not create a phantom stamp
        assert d.age_s("missing") is None

    def test_expired_keys_is_non_destructive(self) -> None:
        clock = _FakeClock()
        d: TtlDict[str] = TtlDict(clock=clock)
        d["old"] = "x"
        clock.advance(61.0)
        d["fresh"] = "y"
        assert d.expired_keys(60.0) == ["old"]
        assert "old" in d  # still present — expired_keys only reports

    def test_sweep_evicts_only_expired(self) -> None:
        clock = _FakeClock()
        d: TtlDict[str] = TtlDict(clock=clock)
        d["old"] = "x"
        clock.advance(61.0)
        d["fresh"] = "y"
        evicted = d.sweep(60.0)
        assert evicted == ["old"]
        assert "old" not in d
        assert d["fresh"] == "y"

    def test_exactly_ttl_old_is_kept(self) -> None:
        # Strictly-older-than semantics: an entry aged EXACTLY ttl survives.
        clock = _FakeClock()
        d: TtlDict[str] = TtlDict(clock=clock)
        d["a"] = "x"
        clock.advance(60.0)
        assert d.sweep(60.0) == []
        assert "a" in d

    def test_non_positive_ttl_disables_sweep(self) -> None:
        # The knob convention (#611/#801): <= 0 means "never reap",
        # never "reap instantly".
        clock = _FakeClock()
        d: TtlDict[str] = TtlDict(clock=clock)
        d["a"] = "x"
        clock.advance(10_000_000.0)
        assert d.sweep(0.0) == []
        assert d.sweep(-5.0) == []
        assert "a" in d

    def test_injected_now_overrides_clock(self) -> None:
        clock = _FakeClock(start=1_000.0)
        d: TtlDict[str] = TtlDict(clock=clock)
        d["a"] = "x"
        assert d.sweep(60.0, now=1_061.0) == ["a"]
