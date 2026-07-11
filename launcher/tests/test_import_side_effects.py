"""#783 — importing ``launcher.__main__`` must be side-effect-free at exit.

The regression this locks: ``atexit.register(_cleanup)`` sat at MODULE scope,
so every process that merely imported ``launcher.__main__`` — every standing-
gate pytest run collects a dozen such files — armed the full production
teardown at interpreter exit.  With the #657-era ``policy=always`` ratchet,
that teardown issues a real ``Stop-VM`` against BlarAI-Orchestrator whenever
the VM happens to be Running.  Three gate runs on 2026-07-09 each force-stopped
the live guest VM (first night the VM was deliberately kept up for the #744
guest oracle).  LOCALAPPDATA redirection scopes DATA; the hypervisor is shared
state (BUILD_JOURNAL lesson 224 class).

The lock runs a CHILD interpreter so the atexit machinery actually fires:

* ``test_bare_import_registers_no_cleanup`` — child imports the module, plants
  recorders on the VM seams, exits normally.  Recorder file must NOT appear.
* ``test_detector_fires_when_cleanup_is_registered`` — positive control
  (lesson 222): a sibling child registers ``_cleanup`` explicitly; the SAME
  recorder MUST fire.  Proves a silent pass above is a real absence, not a
  broken probe.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

# The child plants recorders on the exact seams _cleanup touches on its VM leg.
# get_vm_state returns OFF so the probe never escalates to a real Stop-VM even
# if the regression is present — the recorder file alone is the verdict.
_CHILD_COMMON = """
import sys
sys.path.insert(0, {root!r})
import launcher.__main__ as m

marker = sys.argv[1]

def _recording_get_vm_state(*a, **k):
    with open(marker, "a", encoding="utf-8") as fh:
        fh.write("get_vm_state\\n")
    return m.VMState.OFF

def _recording_stop_vm(*a, **k):
    with open(marker, "a", encoding="utf-8") as fh:
        fh.write("stop_vm\\n")
    return True

m.get_vm_state = _recording_get_vm_state
m.stop_vm = _recording_stop_vm
"""

_CHILD_REGISTERED = _CHILD_COMMON + """
import atexit
atexit.register(m._cleanup)
"""


def _run_child(body: str, marker: Path) -> None:
    code = body.format(root=_REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", code, str(marker)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"child interpreter failed (rc={proc.returncode}):\n{proc.stderr}"
    )


def test_bare_import_registers_no_cleanup(tmp_path: Path) -> None:
    """A bare import + normal exit must never reach the VM seams."""
    marker = tmp_path / "cleanup-ran.txt"
    _run_child(_CHILD_COMMON, marker)
    assert not marker.exists(), (
        "importing launcher.__main__ armed _cleanup at interpreter exit — "
        f"the VM seams were touched: {marker.read_text(encoding='utf-8')!r}. "
        "atexit.register(_cleanup) belongs inside main() (#783)."
    )


def test_detector_fires_when_cleanup_is_registered(tmp_path: Path) -> None:
    """Positive control: with _cleanup registered, the same recorder fires."""
    marker = tmp_path / "cleanup-ran.txt"
    _run_child(_CHILD_REGISTERED, marker)
    assert marker.exists(), (
        "positive control failed — _cleanup was registered yet the recorder "
        "never fired; the bare-import test above cannot be trusted."
    )
    assert "get_vm_state" in marker.read_text(encoding="utf-8")


def test_main_still_registers_cleanup() -> None:
    """The production teardown must still be armed by main() (not lost)."""
    import launcher.__main__ as m
    import inspect

    src = inspect.getsource(m.main)
    assert "atexit.register(_cleanup)" in src, (
        "main() no longer registers _cleanup — the launcher would leak "
        "services/VM on exit (#783 moved the registration here; it must stay)."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
