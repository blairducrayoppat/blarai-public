#!/usr/bin/env bash
# Throwaway driver — CACHE_DIR empirical probe (Vikunja #545, voice handoff §7.1).
# ON-AC measurement only: battery throttles absolute load times. Each pipeline
# load runs in a SEPARATE process so cold/warm timing is not contaminated by
# in-process GPU/runtime warm state. prod = CACHE_DIR="" (production); cold/warm
# = CACHE_DIR=<ovcache>. The only variable across runs is CACHE_DIR.
set -u
PY=.venv/Scripts/python.exe
PROBE=userdata/_cache_probe/cache_probe.py
OUT=userdata/_cache_probe
CACHE=userdata/_cache_probe/ovcache   # throwaway, gitignored

echo "=== CACHE_DIR probe START: $(date) ==="

echo "--- prod1 (CACHE_DIR=\"\") ---"
$PY $PROBE run --mode prod  --label prod1 --out $OUT/run_prod1.json
echo "--- prod2 (CACHE_DIR=\"\") ---"
$PY $PROBE run --mode prod  --label prod2 --out $OUT/run_prod2.json

echo "--- clearing cache dir for a true cold compile ---"
rm -rf "$CACHE"; mkdir -p "$CACHE"
echo "--- cold (CACHE_DIR empty -> compiles + writes blob) ---"
$PY $PROBE run --mode cache --cache-dir $CACHE --label cold  --out $OUT/run_cold.json

echo "--- warm1 (CACHE_DIR populated -> loads blob) ---"
$PY $PROBE run --mode cache --cache-dir $CACHE --label warm1 --out $OUT/run_warm1.json
echo "--- warm2 (CACHE_DIR populated -> loads blob) ---"
$PY $PROBE run --mode cache --cache-dir $CACHE --label warm2 --out $OUT/run_warm2.json

echo "=== COMPARE: $(date) ==="
$PY $PROBE compare --dir $OUT
echo "=== DONE: $(date) ==="
