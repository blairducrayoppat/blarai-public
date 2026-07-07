"""Guest-resident Cleaner parser package (UC-003 Stage C, ADR-030 §3).

Runs inside the Alpine Hyper-V guest: hostile fetched HTML is parsed here,
never in a host process.  Alpine 3.21 / Python 3.12 / lxml 5.3.0 — stdlib +
trafilatura/lxml only; no host paths, no Windows-isms.
"""
