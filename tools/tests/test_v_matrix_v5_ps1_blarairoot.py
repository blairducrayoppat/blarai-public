"""V matrix V5 -- PS1 -BlarAIRoot AST-driven probe.

Re-invokes the proven verify_25_v2.ps1 probe (Stage 2.5.v2 deliverable) which
parses each refactored PS1 with the PowerShell AST, extracts ONLY the primary
``RepoRoot`` / ``BlarAIRoot`` ``ParameterAst`` (full Extent text including
``[Alias()]`` and ``[string]`` attributes plus default expression), then
constructs a minimal single-param probe scriptblock that isolates env-fallback
/ alias-binding / explicit-precedence semantics across 6 PS1 entrypoints
(plus McpConfigPath derivation on 2 of them).

Strategy per Guide-#6 g2: subprocess.run the existing verify_25_v2.ps1 +
assert the ``ALL_GREEN`` trailer string is present. Re-uses the proven probe
end-to-end without re-implementing AST parsing in Python.

Skipped on non-Windows (PowerShell + the BlarAI repo cwd are pre-conditions).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PS1 = REPO_ROOT / "scripts" / "verify_25_v2.ps1"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell probe is Windows-only")
def test_verify_25_v2_probe_emits_all_green() -> None:
    """Run scripts/verify_25_v2.ps1; assert ALL_GREEN trailer is present."""
    if not PROBE_PS1.is_file():
        pytest.fail(f"Expected probe script at {PROBE_PS1}; not found.")

    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("Neither pwsh nor powershell on PATH")

    result = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROBE_PS1),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"verify_25_v2.ps1 exited non-zero: rc={result.returncode}\n"
        f"output:\n{combined}"
    )
    assert "ALL_GREEN" in combined, (
        f"verify_25_v2.ps1 did not emit ALL_GREEN trailer.\n"
        f"output:\n{combined}"
    )
