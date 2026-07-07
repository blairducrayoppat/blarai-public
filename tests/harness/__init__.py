"""Headless scenario + latency harness for BlarAI (Vikunja #563).

A GUI-free way to drive the real backend in-process and measure what a user
feels. Two layers:

- **Layer A — regression locks** (this package's ``test_freeze_regression.py``):
  deterministic, no models, runs in the default ``pytest`` suite. Drives the
  real :class:`~services.ui_backend.src.dispatcher.RpcDispatcher` through an
  injected fake gateway to prove behavioural contracts — first among them that
  image-attach runs OFF the event loop and cannot freeze voice + chat behind it
  (locks commit ``f4406c5``; BUILD_JOURNAL lesson 24).

- **Layer B — real-model latency** (``test_real_model_latency.py``, marked
  ``slow`` + ``hardware``, deselected by default): loads the real OpenVINO
  models on the Arc 140V and records community-grade latency numbers to
  ``docs/performance/``. This is the "boot BlarAI and see the issue without the
  User-Operator" capability — run it with ``pytest -m hardware tests/harness``
  or ``python -m tests.harness``.

The driver injects the gateway/store/voice, so the SAME machinery serves the
deterministic locks and the real-model benchmarks.
"""

from __future__ import annotations
