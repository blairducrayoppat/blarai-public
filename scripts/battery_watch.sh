#!/usr/bin/env bash
# Active battery watchdog. Exits (and therefore NOTIFIES) the moment anything
# notable happens, rather than sleeping through a dead run.
#
# Trigger conditions, each drawn from a failure actually hit on 2026-08-07:
#   DONE     - the runner wrote its exit line
#   STALL    - no CANDIDATE WRITES for STALL_MIN minutes. Progress is measured by the
#              worktree, NOT the fleet journal: the journal writes only TASK-START and
#              TASK-END, so it sits unchanged for the whole build and looks frozen.
#              Measured 2026-08-07: a healthy candidate wrote styles.css, index.html, a
#              test and home.html across twelve minutes while the journal never moved.
#   STARVED  - available RAM under 1 GB on TWO consecutive polls. A 30B coder on a
#              31.3 GB box legitimately drives free memory to ~0 while loading -- measured
#              0.08 GB, recovered to 4.99 unaided -- so a single low reading is the
#              EXPECTED condition, not a fault. Only a sustained one is.
#   HEARTBEAT- nothing wrong, MAX_MIN elapsed: report progress and re-arm. A watchdog
#              that speaks only on failure cannot be told apart from one that has died.
#
# Usage: battery_watch.sh <night-dir> [stall_min] [max_min]

NIGHT="$1"
STALL_MIN="${2:-20}"
MAX_MIN="${3:-25}"

LAUNCHER="$NIGHT/launcher.log"
started=$(date +%s)
last_sig=""
last_change=$(date +%s)
starved_once="no"

fleet_dir() { ls -dt /c/Users/mrbla/agentic-setup/state/fleet-runs/*/ 2>/dev/null | head -1; }
worktree_dir() { ls -dt /c/Users/mrbla/agentic-setup/state/worktrees/*/ 2>/dev/null | head -1; }

while true; do
  sleep 30
  now=$(date +%s)

  # ---- DONE -------------------------------------------------------------------
  if grep -q "battery runner exit" "$LAUNCHER" 2>/dev/null; then
    echo "TRIGGER=DONE at $(date '+%H:%M:%S')"
    tail -6 "$LAUNCHER"
    echo "--- scorecards ---"
    ls "$NIGHT/scorecards" 2>/dev/null
    exit 0
  fi

  # ---- STARVED (sustained only) ------------------------------------------------
  avail=$(powershell -NoProfile -Command "[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)" 2>/dev/null | tr -d '\r')
  if [ -n "$avail" ] && awk -v a="$avail" 'BEGIN{exit !(a < 1)}'; then
    if [ "$starved_once" = "yes" ]; then
      echo "TRIGGER=STARVED at $(date '+%H:%M:%S') — available ${avail} GB on two consecutive polls"
      powershell -NoProfile -Command "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 Id,ProcessName,@{n='GB';e={[math]::Round(\$_.WorkingSet64/1GB,2)}} | Format-Table -AutoSize | Out-String" 2>/dev/null
      exit 0
    fi
    starved_once="yes"
  else
    starved_once="no"
  fi

  # ---- progress signature ------------------------------------------------------
  WT=$(worktree_dir)
  J=$(fleet_dir)
  sig=""
  [ -n "$WT" ] && sig=$(find "$WT" -type f -not -path "*/.git/*" -printf '%T@ %p\n' 2>/dev/null | sort -r | head -1)
  [ -n "$J" ] && [ -f "$J/journal.log" ] && sig="$sig|$(wc -c < "$J/journal.log" 2>/dev/null)"
  if [ "$sig" != "$last_sig" ]; then
    last_sig="$sig"
    last_change=$now
  fi

  # ---- STALL -------------------------------------------------------------------
  if [ $(( (now - last_change) / 60 )) -ge "$STALL_MIN" ]; then
    echo "TRIGGER=STALL at $(date '+%H:%M:%S') — no candidate writes for ${STALL_MIN}m"
    echo "newest worktree write: ${sig%%|*}"
    [ -n "$J" ] && { echo "--- journal ---"; tail -2 "$J/journal.log" 2>/dev/null; }
    echo "--- launcher tail ---"; tail -4 "$LAUNCHER" 2>/dev/null
    exit 0
  fi

  # ---- HEARTBEAT ---------------------------------------------------------------
  if [ $(( (now - started) / 60 )) -ge "$MAX_MIN" ]; then
    echo "TRIGGER=HEARTBEAT at $(date '+%H:%M:%S') — running $(( (now - started) / 60 ))m, healthy"
    echo "available RAM: ${avail} GB"
    echo "newest worktree write: ${sig%%|*}"
    [ -n "$J" ] && echo "run: $(basename "$J")"
    exit 0
  fi
done
