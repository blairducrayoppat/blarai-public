#!/bin/sh
set -eu

RUNTIME_ROOT="${1:-/opt/blarai}"
BUNDLE_PATH="${2:-/opt/blarai/runtime_bundle.zip}"
EVIDENCE_DIR="${RUNTIME_ROOT}/evidence"
STARTUP_EVIDENCE="${EVIDENCE_DIR}/priority5_guest_startup.json"

mkdir -p "${RUNTIME_ROOT}" "${EVIDENCE_DIR}"

if [ ! -f "${BUNDLE_PATH}" ]; then
  echo "ERROR: runtime bundle not found at ${BUNDLE_PATH}" >&2
  exit 10
fi

python3 - "${BUNDLE_PATH}" "${RUNTIME_ROOT}" <<'PY'
import json
import sys
import zipfile
from pathlib import Path

bundle = Path(sys.argv[1])
runtime_root = Path(sys.argv[2])

with zipfile.ZipFile(bundle, "r") as zip_obj:
    zip_obj.extractall(runtime_root)

manifest = {
    "status": "extracted",
    "bundle": str(bundle),
    "runtime_root": str(runtime_root),
}
print(json.dumps(manifest))
PY

python3 "${RUNTIME_ROOT}/scripts/guest/guest_startup_smoke.py" \
  --runtime-root "${RUNTIME_ROOT}" \
  --output "${STARTUP_EVIDENCE}"

echo "Priority-5 guest runtime bootstrap completed"
