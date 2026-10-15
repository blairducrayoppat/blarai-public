#!/bin/bash
# Exploratory: the standing selection split into two concurrent pytest processes. Not a recorded figure.
cd /c/Users/__USER__/BlarAI-worktrees/gate-fixed-f407d2af || exit 1
PY=/c/Users/__USER__/BlarAI/.venv/Scripts/python.exe
OUT=/c/Users/__USER__/BlarAI-worktrees/_gatelogs/ptrial
mkdir -p "$OUT"
GITFILES=$(ls tests/security/test_git_*.py tests/security/test_install_git_hooks_batching.py)
IGN=""
for f in $GITFILES; do IGN="$IGN --ignore=$f"; done
date '+%T' > "$OUT/start"
( export LOCALAPPDATA="$OUT/la-a"; mkdir -p "$LOCALAPPDATA"; PYTHONUNBUFFERED=1 $PY -u -m pytest $GITFILES -m "not hardware and not winui and not slow" -p no:cacheprovider --durations=0 -q -rfs > "$OUT/a-git.log" 2>&1; date '+%T' > "$OUT/a-end" ) &
( export LOCALAPPDATA="$OUT/la-b"; mkdir -p "$LOCALAPPDATA"; PYTHONUNBUFFERED=1 $PY -u -m pytest shared/ services/ launcher/ tests/integration/ tests/security/ $IGN -m "not hardware and not winui and not slow" -p no:cacheprovider --durations=0 -q -rfs > "$OUT/b-rest.log" 2>&1; date '+%T' > "$OUT/b-end" ) &
wait
date '+%T' > "$OUT/end"
