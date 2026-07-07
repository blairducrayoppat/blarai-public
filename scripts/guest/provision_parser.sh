#!/bin/sh
# BlarAI UC-003 Stage C — guest parser provisioning (Alpine 3.21, IN-GUEST)
# =========================================================================
# Run as root INSIDE the BlarAI-Orchestrator guest during the controlled
# session (after the step-0 VHDX backup).  Idempotent: safe to re-run; each
# step checks before it changes.
#
# Two-phase by design (the guest is NIC-less, so wheels arrive from the host
# over Copy-VMFile, which itself needs hv_fcopy_daemon enabled HERE first):
#
#   Phase 1 (always): apk packages, hv_fcopy_daemon enablement, directory
#       layout, OpenRC service install.  If the wheel directory is not yet
#       staged, the script exits 20 with instructions — ship wheels from the
#       host (scripts/ship_parser_files.ps1) and RE-RUN.
#   Phase 2 (wheels present): SHA256SUMS verification, venv creation, pinned
#       pip install (offline: --no-index --no-deps --find-links), import +
#       version verification, evidence JSON.
#
# Fail-closed: set -e; every verification failure aborts with a distinct
# exit code.  This script makes NO network calls (apk uses the local media /
# pre-synced repo only if available — see the note at step 1).

set -eu

PARSER_ROOT="${1:-/opt/blarai/parser}"
PROVISION_DIR="${PARSER_ROOT}/provision"
WHEEL_DIR="${PARSER_ROOT}/wheels"
VENV_DIR="${PARSER_ROOT}/venv"
EVIDENCE_DIR="${PARSER_ROOT}/evidence"
BIN_DIR="${PARSER_ROOT}/bin"
EVIDENCE_FILE="${EVIDENCE_DIR}/provision.json"

log() { echo "[provision_parser] $*"; }
die() { echo "[provision_parser] FATAL: $*" >&2; exit "${2:-1}"; }

[ "$(id -u)" = "0" ] || die "must run as root" 2

# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------

# 1. Packages.  NOTE: the guest is NIC-less — `apk add` works only if the
#    packages are already present in the apk cache / local media, OR the
#    controlled session temporarily uses the Alpine install ISO repo.  #655
#    c.1045 recorded: Alpine 3.21 / Python 3.12; `apk add py3-lxml` yields
#    lxml 5.3.0.  hvtools provides hv_fcopy_daemon (the Copy-VMFile guest
#    half); py3-pip provides pip for the venv (Alpine may omit ensurepip).
log "step 1: apk packages (python3, py3-pip, py3-lxml, hvtools)"
apk add --no-progress python3 py3-pip py3-lxml hvtools \
    || die "apk add failed - packages must be available offline (cache/media); see the provisioning record" 10

PYVER="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
log "python3 = ${PYVER}"
case "$PYVER" in
    3.12.*|3.13.*) : ;;
    *) log "WARNING: expected Python 3.12.x on Alpine 3.21, got ${PYVER} (continuing)";;
esac

# 2. Enable the Copy-VMFile guest half persistently.  This is the exact gap
#    behind the 2026-02-25 P5_GUEST_CHANNEL_NOT_READY failure: hvtools was
#    installed but the fcopy daemon was never enabled/started.
log "step 2: enable + start hv_fcopy_daemon (Copy-VMFile guest half)"
rc-update add hv_fcopy_daemon default 2>/dev/null || true
rc-service hv_fcopy_daemon start 2>/dev/null || rc-service hv_fcopy_daemon restart \
    || die "hv_fcopy_daemon failed to start - Copy-VMFile deploys cannot work" 11
rc-service hv_fcopy_daemon status || true

# 3. Directory layout.
log "step 3: directory layout under ${PARSER_ROOT}"
mkdir -p "${PARSER_ROOT}/incoming" "${PARSER_ROOT}/releases" \
         "${EVIDENCE_DIR}" "${BIN_DIR}" "${WHEEL_DIR}" "${PROVISION_DIR}"

# 4. Install the supervisor + OpenRC service (files shipped from the host
#    into ${PROVISION_DIR} by scripts/ship_parser_files.ps1).
log "step 4: install supervisor + OpenRC service"
[ -f "${PROVISION_DIR}/parser_supervisor.sh" ] \
    || die "missing ${PROVISION_DIR}/parser_supervisor.sh - ship scripts/guest/ from the host first" 12
[ -f "${PROVISION_DIR}/blarai-parser.initd" ] \
    || die "missing ${PROVISION_DIR}/blarai-parser.initd - ship scripts/guest/ from the host first" 12
install -m 0755 "${PROVISION_DIR}/parser_supervisor.sh" "${BIN_DIR}/parser_supervisor.sh"
install -m 0755 "${PROVISION_DIR}/blarai-parser.initd" /etc/init.d/blarai-parser
rc-update add blarai-parser default 2>/dev/null || true

# ---------------------------------------------------------------------------
# Phase 2 (wheels staged?)
# ---------------------------------------------------------------------------

if [ ! -f "${WHEEL_DIR}/SHA256SUMS" ]; then
    log "wheels not staged yet (${WHEEL_DIR}/SHA256SUMS missing)."
    log "From the HOST run:"
    log "  scripts/stage_parser_wheels.ps1"
    log "  scripts/ship_parser_files.ps1 -SourceDir build/guest_parser_wheels -GuestDir ${WHEEL_DIR}"
    log "then RE-RUN this script.  Phase 1 is complete and idempotent."
    exit 20
fi

# 5. Verify the host->guest transfer integrity of every staged file.
log "step 5: verify staged wheels (sha256sum -c SHA256SUMS)"
( cd "${WHEEL_DIR}" && sha256sum -c SHA256SUMS ) \
    || die "wheel manifest verification FAILED - refusing to install (re-ship from the host)" 21
[ -f "${WHEEL_DIR}/guest-parser.txt" ] \
    || die "guest-parser.txt missing from the wheel dir" 21

# 6. venv with system site-packages so the apk lxml is visible (and so the
#    system pip module is usable even if Alpine's venv lacks ensurepip).
log "step 6: venv (${VENV_DIR}, --system-site-packages)"
[ -x "${VENV_DIR}/bin/python" ] || python3 -m venv --system-site-packages "${VENV_DIR}" \
    || die "venv creation failed" 22

# 7. Offline pinned install: full closure listed, no resolution, no index.
log "step 7: pip install (offline, pinned, --no-deps full closure)"
"${VENV_DIR}/bin/python" -m pip install \
    --no-index --no-deps \
    --find-links "${WHEEL_DIR}" \
    -r "${WHEEL_DIR}/guest-parser.txt" \
    || die "offline pip install failed" 23

# 8. Verify imports + versions; write evidence.
log "step 8: import + version verification"
if ! "${VENV_DIR}/bin/python" - "$EVIDENCE_FILE" <<'PY'
import json
import sys

evidence_path = sys.argv[1]

import lxml.etree
import trafilatura
import courlan
import htmldate
import justext
import dateparser
import charset_normalizer

lxml_version = lxml.etree.__version__
versions = {
    "python": "%d.%d.%d" % sys.version_info[:3],
    "lxml": str(lxml_version),
    "trafilatura": trafilatura.__version__,
    "courlan": courlan.__version__,
    "htmldate": htmldate.__version__,
    "justext": getattr(justext, "__version__", "unknown"),
    "dateparser": dateparser.__version__,
    "charset_normalizer": charset_normalizer.__version__,
}

errors = []
if versions["trafilatura"] != "2.1.0":
    errors.append("trafilatura != 2.1.0: %s" % versions["trafilatura"])
if tuple(int(p) for p in str(lxml_version).split(".")[:2]) < (5, 3):
    errors.append("lxml < 5.3 (trafilatura 2.1.0 floor): %s" % lxml_version)

payload = {
    "artifact": "guest parser provisioning evidence (#655 Stage C)",
    "disposition": "FAIL" if errors else "PASS",
    "versions": versions,
    "errors": errors,
}
with open(evidence_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
print(json.dumps(payload, indent=2))
sys.exit(1 if errors else 0)
PY
then
    die "import/version verification FAILED (see ${EVIDENCE_FILE})" 24
fi

# 9. Start (or restart) the supervisor service.  With no deploy yet it idles
#    waiting for the first bundle - that is its designed steady state.
log "step 9: start blarai-parser (OpenRC)"
rc-service blarai-parser restart 2>/dev/null || rc-service blarai-parser start \
    || die "blarai-parser OpenRC service failed to start" 25

log "PROVISION OK - evidence: ${EVIDENCE_FILE}"
log "Next (HOST side): register the parser hv_sock service GUID"
log "  (scripts/register_parser_vsock_service.ps1), then deploy via the"
log "  launcher ([guest_parser] enabled=true) or wait for the integration."
exit 0
