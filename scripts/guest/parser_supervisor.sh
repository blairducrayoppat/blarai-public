#!/bin/sh
# BlarAI UC-003 Stage C — guest parser supervisor (Alpine, busybox sh; #655)
# ==========================================================================
# The guest half of the no-exec-channel deploy design (ADR-030 §3 / the
# provisioning record): the host can only SHIP FILES into this guest
# (Copy-VMFile); it cannot run commands.  This supervisor — installed once by
# provision_parser.sh and run by the blarai-parser OpenRC service — closes
# that gap by acting on what the host ships:
#
#   * DEPLOY: when incoming/deploy.trigger exists AND incoming/bundle.zip
#     verifies against incoming/bundle.sha256, extract to releases/<epoch>,
#     atomically repoint the `current` symlink, clear incoming, and restart
#     the parser child.  The trigger is the COMMIT POINT (the host copies it
#     last), so a partially-shipped deploy is never applied.  A bundle that
#     fails verification is quarantined to incoming/rejected.<epoch> and the
#     running release is left untouched.
#   * RUN: keep the parser child (venv python -m $ENTRY_MODULE, from
#     current/service.conf) running.  Crash policy is FAIL-CLOSED: after
#     MAX_CRASHES within CRASH_WINDOW_S the supervisor EXITS — the vsock
#     listener disappears, the host health check fails, and URL-mode ingest
#     refuses.  No infinite-restart masking.
#
# No network use of any kind: the guest is NIC-less; the parser child binds
# AF_VSOCK only (port from service.conf, exported as
# BLARAI_PARSER_VSOCK_PORT).

set -u

PARSER_ROOT="${PARSER_ROOT:-/opt/blarai/parser}"
INCOMING="${PARSER_ROOT}/incoming"
RELEASES="${PARSER_ROOT}/releases"
CURRENT="${PARSER_ROOT}/current"
VENV="${PARSER_ROOT}/venv"
RUN_DIR="${PARSER_ROOT}/run"
EVIDENCE_DIR="${PARSER_ROOT}/evidence"
LOG_FILE="${EVIDENCE_DIR}/supervisor.log"
CHILD_PID_FILE="${RUN_DIR}/child.pid"

POLL_INTERVAL_S=2
MAX_CRASHES=3
CRASH_WINDOW_S=120
KEEP_RELEASES=2

mkdir -p "$INCOMING" "$RELEASES" "$RUN_DIR" "$EVIDENCE_DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG_FILE"; }

child_pid=""
crash_count=0
crash_window_start=0

stop_child() {
    if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
        log "stopping parser child (pid $child_pid)"
        kill "$child_pid" 2>/dev/null || true
        # bounded graceful wait, then hard kill
        i=0
        while kill -0 "$child_pid" 2>/dev/null && [ "$i" -lt 10 ]; do
            sleep 1; i=$((i + 1))
        done
        kill -9 "$child_pid" 2>/dev/null || true
    fi
    child_pid=""
    rm -f "$CHILD_PID_FILE"
}

on_term() {
    log "TERM received - stopping child and exiting"
    stop_child
    exit 0
}
trap on_term TERM INT

quarantine_incoming() {
    ts="$(date +%s)"
    qdir="${INCOMING}/rejected.${ts}"
    mkdir -p "$qdir"
    for f in deploy.trigger bundle.zip bundle.sha256; do
        [ -f "${INCOMING}/$f" ] && mv "${INCOMING}/$f" "$qdir/" 2>/dev/null
    done
    log "deploy REJECTED - quarantined to $qdir (running release untouched)"
}

apply_incoming() {
    # Returns 0 only when a NEW release was applied.
    [ -f "${INCOMING}/deploy.trigger" ] || return 1
    if [ ! -f "${INCOMING}/bundle.zip" ] || [ ! -f "${INCOMING}/bundle.sha256" ]; then
        log "trigger present without complete bundle - quarantining"
        quarantine_incoming
        return 1
    fi
    if ! ( cd "$INCOMING" && sha256sum -c bundle.sha256 >/dev/null 2>&1 ); then
        log "bundle sha256 verification FAILED"
        quarantine_incoming
        return 1
    fi

    ts="$(date +%s)"
    dest="${RELEASES}/${ts}"
    mkdir -p "$dest"
    if ! python3 - "${INCOMING}/bundle.zip" "$dest" <<'PY'
import sys
import zipfile
from pathlib import Path

bundle, dest = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
with zipfile.ZipFile(bundle, "r") as zf:
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not str(target).startswith(str(dest)):
            raise SystemExit("zip-slip refused: %s" % member.filename)
    zf.extractall(dest)
PY
    then
        log "bundle extraction FAILED"
        rm -rf "$dest"
        quarantine_incoming
        return 1
    fi
    if [ ! -f "${dest}/service.conf" ]; then
        log "bundle has no service.conf - rejecting"
        rm -rf "$dest"
        quarantine_incoming
        return 1
    fi

    ln -sfn "$dest" "$CURRENT"
    rm -f "${INCOMING}/deploy.trigger" "${INCOMING}/bundle.zip" "${INCOMING}/bundle.sha256"
    log "release applied: $dest"

    # prune old releases (keep newest $KEEP_RELEASES)
    count=0
    for rel in $(ls -1dr "${RELEASES}"/* 2>/dev/null); do
        count=$((count + 1))
        [ "$count" -le "$KEEP_RELEASES" ] && continue
        rm -rf "$rel"
        log "pruned old release: $rel"
    done
    return 0
}

start_child() {
    [ -f "${CURRENT}/service.conf" ] || return 1
    ENTRY_MODULE=""
    VSOCK_PORT=""
    # service.conf is host-authored (trusted direction) KEY=VALUE.
    . "${CURRENT}/service.conf"
    if [ -z "${ENTRY_MODULE}" ] || [ -z "${VSOCK_PORT}" ]; then
        log "service.conf missing ENTRY_MODULE/VSOCK_PORT - cannot start (fail-closed)"
        return 1
    fi
    if [ ! -x "${VENV}/bin/python" ]; then
        log "venv python missing (${VENV}/bin/python) - run provision_parser.sh"
        return 1
    fi
    log "starting parser child: -m ${ENTRY_MODULE} (vsock port ${VSOCK_PORT})"
    cd "${CURRENT}"
    BLARAI_PARSER_VSOCK_PORT="${VSOCK_PORT}" \
    PYTHONPATH="${CURRENT}" \
        "${VENV}/bin/python" -m "${ENTRY_MODULE}" \
        >> "${EVIDENCE_DIR}/parser.out.log" 2>> "${EVIDENCE_DIR}/parser.err.log" &
    child_pid=$!
    echo "$child_pid" > "$CHILD_PID_FILE"
    return 0
}

note_crash() {
    now="$(date +%s)"
    if [ "$crash_window_start" -eq 0 ] || [ $((now - crash_window_start)) -gt "$CRASH_WINDOW_S" ]; then
        crash_window_start="$now"
        crash_count=1
    else
        crash_count=$((crash_count + 1))
    fi
    log "parser child exited (crash ${crash_count}/${MAX_CRASHES} in window)"
    if [ "$crash_count" -ge "$MAX_CRASHES" ]; then
        log "FAIL-CLOSED: ${MAX_CRASHES} crashes within ${CRASH_WINDOW_S}s - supervisor exiting; host health checks will now fail and URL-mode ingest refuses"
        stop_child
        exit 1
    fi
}

log "supervisor up (root=${PARSER_ROOT})"

while :; do
    if apply_incoming; then
        stop_child
    fi
    if [ -f "${CURRENT}/service.conf" ]; then
        if [ -z "$child_pid" ] || ! kill -0 "$child_pid" 2>/dev/null; then
            if [ -n "$child_pid" ]; then
                note_crash
                child_pid=""
                rm -f "$CHILD_PID_FILE"
            fi
            start_child || true
        fi
    fi
    sleep "$POLL_INTERVAL_S"
done
