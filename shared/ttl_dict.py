"""
TtlDict — a dict that remembers WHEN each key was written (#801).
=================================================================
The session-lifecycle audit (Vikunja #801, System Qualities Audit Stability
#1/#3/#5) found a family of session-keyed coordinator dicts that grow one
entry per session and are cleared only by the completion pop — an abandoned
session's entry is resident until process restart. This mapping is the shared
backstop primitive: a drop-in ``MutableMapping[str, V]`` whose ``__setitem__``
stamps a monotonic write time, plus a ``sweep`` that evicts entries older
than a TTL.

Design constraints (match ``shared/``): stdlib only, importing has no side
effects, strict typing.

Semantics:
  * The stamp is the LAST WRITE (``d[k] = v`` or ``touch``), not last read —
    a read does not signal the entry is still wanted; a write does. Callers
    that mutate a stored value in place (``d[k].append(...)``) must ``touch``
    to refresh the stamp.
  * ``sweep(ttl_s)`` with ``ttl_s <= 0`` is a no-op (TTL disabled) — mirrors
    the ``embed_cache_idle_unload_s`` convention (#611): a non-positive knob
    means "never reap", never "reap instantly".
  * Time is ``time.monotonic`` (injectable for tests): immune to wall-clock
    steps, so an NTP/DST jump can never mass-expire live state. On a machine
    that sleeps, monotonic time may exclude the slept interval — idle is then
    measured in awake-time, which only makes the backstop MORE conservative.
  * Fail-safe by construction: only stamped keys are ever swept, and every
    write stamps — an entry can never be evicted without a provable age.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, MutableMapping
from typing import Callable, Generic, TypeVar

V = TypeVar("V")


class TtlDict(MutableMapping[str, V], Generic[V]):
    """A ``str``-keyed mapping with per-key write timestamps and TTL sweep.

    Drop-in for a plain ``dict[str, V]`` at every ``MutableMapping`` call
    site (``[]``, ``get``, ``pop``, ``setdefault``, ``in``, iteration).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[str, V] = {}
        self._stamps: dict[str, float] = {}
        self._clock: Callable[[], float] = clock

    # ── MutableMapping protocol ───────────────────────────────────────────

    def __setitem__(self, key: str, value: V) -> None:
        self._data[key] = value
        self._stamps[key] = self._clock()

    def __getitem__(self, key: str) -> V:
        return self._data[key]

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        # A key present without a stamp cannot arise through this API, but a
        # missing stamp must never make deletion fail (cleanup always works).
        self._stamps.pop(key, None)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:  # pragma: no cover — debug aid only
        return f"TtlDict({self._data!r})"

    # ── TTL surface ───────────────────────────────────────────────────────

    def touch(self, key: str) -> None:
        """Refresh *key*'s stamp to now (no-op for an absent key).

        Call after mutating a stored value in place — e.g. appending to a
        stored list — so activity on the entry defers its expiry.
        """
        if key in self._data:
            self._stamps[key] = self._clock()

    def age_s(self, key: str, now: float | None = None) -> float | None:
        """Seconds since *key* was last written, or ``None`` if absent."""
        stamp = self._stamps.get(key)
        if stamp is None:
            return None
        current = self._clock() if now is None else now
        return current - stamp

    def expired_keys(self, ttl_s: float, now: float | None = None) -> list[str]:
        """Keys whose last write is older than *ttl_s* (non-destructive).

        ``ttl_s <= 0`` disables expiry and returns ``[]``.
        """
        if ttl_s <= 0:
            return []
        current = self._clock() if now is None else now
        return [k for k, stamp in self._stamps.items() if current - stamp > ttl_s]

    def sweep(self, ttl_s: float, now: float | None = None) -> list[str]:
        """Evict every entry older than *ttl_s*; return the evicted keys.

        ``ttl_s <= 0`` disables expiry (returns ``[]``, evicts nothing).
        """
        expired = self.expired_keys(ttl_s, now=now)
        for key in expired:
            del self[key]
        return expired
