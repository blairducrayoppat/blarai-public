<#
.SYNOPSIS
    Compute a live BlarAI Active State snapshot from four data sources and
    print the prospective CLAUDE.md §Active State block to stdout.

.DESCRIPTION
    Companion to docs/runbooks/active_state_refresh.md. Automates SS3 steps
    (a) through (d) and assembles the prospective §Active State block per
    SS5 of the runbook. Does NOT modify CLAUDE.md — writeback is the
    Co-Lead's hand-edit at Sprint Kickoff Phase 3 transition and Sprint
    Close (SCR-authoring) cadences.

    Fail-closed: any failed step (pytest collection error, git not on main,
    Vikunja unreachable, YAML schema unexpected) exits non-zero and prints
    WHICH step failed. No partial-data §Active State blocks are emitted.

    Live-computation-first discipline: prior CLAUDE.md §Active State text
    is NOT read by this script. It is a reference for phrasing convention
    only and that lookup is a human step at writeback time.

.PARAMETER BlarAIRoot
    Absolute path to the BlarAI repo. Default: C:\Users\mrbla\BlarAI.

.PARAMETER VikunjaCliRoot
    Absolute path to tools/vikunja_mcp CLI wrapper root. Default:
    C:\Users\mrbla\BlarAI\tools\vikunja_mcp.

.PARAMETER SkipPytest
    Switch. If set, skips the pytest baseline step (a) and emits a
    "(pytest skipped)" placeholder in the assembled block. Intended for
    smoke-test invocations only; SCR-cadence invocations must include
    pytest.

.EXAMPLE
    cd C:\Users\mrbla\BlarAI
    .\tools\active_state_refresh.ps1

.EXAMPLE
    .\tools\active_state_refresh.ps1 -SkipPytest    # smoke test only

.NOTES
    Procedure: docs/runbooks/active_state_refresh.md
    Cadences:  Co-Lead Sprint Kickoff Phase 3 + Sprint Close (SCR)
    Drift chain: Sprint 8 SWAGR gap #5, Sprint 9 SWAGR gap #4,
                 Sprint 10 SWAGR §15.3 — three-sprint motivation chain
    Author: Sprint 11 EA-2
#>

[CmdletBinding()]
param(
    [string]$BlarAIRoot = 'C:\Users\mrbla\BlarAI',
    [string]$VikunjaCliRoot = 'C:\Users\mrbla\BlarAI\tools\vikunja_mcp',
    [switch]$SkipPytest
)

$ErrorActionPreference = 'Stop'

function Fail-Closed {
    param([string]$Step, [string]$Reason)
    Write-Error "[active_state_refresh] STEP $Step FAILED: $Reason"
    exit 1
}

function Get-PytestBaseline {
    <#
    .SYNOPSIS
        SS3 step (a) — run pytest on shared/services/launcher and extract
        the "<N> passed, <M> skipped" line.
    #>
    if (-not (Test-Path "$BlarAIRoot\.venv\Scripts\pytest.exe")) {
        Fail-Closed -Step '(a)' -Reason ".venv pytest not found under $BlarAIRoot. Activate the venv or fix the path."
    }
    Push-Location $BlarAIRoot
    try {
        $tail = & ".\.venv\Scripts\pytest.exe" 'shared/' 'services/' 'launcher/' '--tb=no' '-q' 2>&1 | Select-Object -Last 10
    } finally {
        Pop-Location
    }
    $summary = $tail | Where-Object { $_ -match '(\d+)\s+passed.*?(\d+)\s+skipped' } | Select-Object -First 1
    if (-not $summary) {
        Fail-Closed -Step '(a)' -Reason "No 'N passed, M skipped' line in pytest tail. Likely a collection error — investigate before refresh."
    }
    if ($summary -match '(\d+)\s+passed.*?(\d+)\s+skipped') {
        return @{ Passed = [int]$Matches[1]; Skipped = [int]$Matches[2]; Raw = $summary.ToString().Trim() }
    }
    Fail-Closed -Step '(a)' -Reason 'Pytest summary regex match failed unexpectedly.'
}

function Get-MainHead {
    <#
    .SYNOPSIS
        SS3 step (b) — capture BlarAI main HEAD and confirm we are on main.
    #>
    Push-Location $BlarAIRoot
    try {
        $branch = (git branch --show-current).Trim()
        if ($branch -ne 'main') {
            Fail-Closed -Step '(b)' -Reason "BlarAI working tree is on '$branch', not 'main'. The refresh runs against main only."
        }
        $log = git log --oneline -3 main
        $head = ($log | Select-Object -First 1).ToString().Split(' ')[0]
        return @{ Head = $head; Log = $log }
    } finally {
        Pop-Location
    }
}

function Get-VikunjaSprintState {
    <#
    .SYNOPSIS
        SS3 step (c) — query Vikunja MCP for active sprint tracking task(s).
        Invokes the existing tools/vikunja_mcp CLI wrapper rather than
        speaking the MCP protocol directly (the CLI wrapper is the
        machine-readable surface this script depends on).
    #>
    $cli = Join-Path $VikunjaCliRoot 'cli.py'
    if (-not (Test-Path $cli)) {
        Fail-Closed -Step '(c)' -Reason "Vikunja MCP CLI wrapper not found at $cli. Confirm tools/vikunja_mcp is installed."
    }
    try {
        $rawList = & python $cli 'list-tasks' '--project-id' '3' '--filter-by' 'done' '--filter-value' 'false' 2>&1
        if ($LASTEXITCODE -ne 0) {
            Fail-Closed -Step '(c)' -Reason "Vikunja MCP list-tasks failed (exit $LASTEXITCODE). Server likely down — check http://localhost:3456."
        }
        return @{ RawList = $rawList -join "`n" }
    } catch {
        Fail-Closed -Step '(c)' -Reason "Exception talking to Vikunja MCP: $_"
    }
}

function Get-ActiveRoster {
    <#
    .SYNOPSIS
        SS3 step (d) — read docs/active_tasks.yaml and extract per-entry
        sprint_id + task_id + continuation_xml.
    #>
    $yamlPath = Join-Path $BlarAIRoot 'docs\active_tasks.yaml'
    if (-not (Test-Path $yamlPath)) {
        Fail-Closed -Step '(d)' -Reason "active_tasks.yaml not found at $yamlPath."
    }
    $raw = Get-Content $yamlPath -Raw
    # Minimal parse: extract task_id / sprint_id / continuation_xml lines.
    # We deliberately do NOT use a full YAML parser — schema is stable per
    # DEC-15 + DEC-16, and any unexpected nesting should trip the schema-
    # drift guard below.
    $entries = @()
    $current = $null
    foreach ($line in (Get-Content $yamlPath)) {
        if ($line -match '^\s*-\s+task_id:\s*(\d+)') {
            if ($current) { $entries += [pscustomobject]$current }
            $current = @{ task_id = [int]$Matches[1] }
        } elseif ($line -match '^\s*sprint_id:\s*(\d+)') {
            if ($current) { $current.sprint_id = [int]$Matches[1] }
        } elseif ($line -match '^\s*continuation_xml:\s*(.+)$') {
            if ($current) { $current.continuation_xml = $Matches[1].Trim() }
        }
    }
    if ($current) { $entries += [pscustomobject]$current }
    if ($entries.Count -eq 0) {
        Fail-Closed -Step '(d)' -Reason 'No active_tasks entries parsed from active_tasks.yaml. Schema unexpected.'
    }
    return @{ Entries = $entries; Raw = $raw }
}

function Format-ActiveStateBlock {
    <#
    .SYNOPSIS
        Assemble the prospective CLAUDE.md §Active State markdown block
        from the four gathered values. Order is fixed (see runbook SS5).
    #>
    param($pytest, $head, $vikunja, $roster)

    $sprintIds = ($roster.Entries | ForEach-Object { $_.sprint_id }) -join ', '
    $taskIds   = ($roster.Entries | ForEach-Object { "#$($_.task_id)" }) -join ', '

    $pytestBullet = if ($SkipPytest) {
        '- **Test baseline**: (pytest skipped — re-run before SCR cadence).'
    } else {
        "- **Test baseline**: **$($pytest.Passed) passed, $($pytest.Skipped) skipped** on ``pytest shared/ services/ launcher/`` (captured at refresh time)."
    }

    $sprintBullet = if ($roster.Entries.Count -gt 1) {
        "- **Sprint state**: Sprints $sprintIds ACTIVE in parallel (Vikunja tracking tasks $taskIds; see ``docs/active_tasks.yaml``)."
    } else {
        $sid = $roster.Entries[0].sprint_id
        $tid = $roster.Entries[0].task_id
        "- **Sprint state**: Sprint $sid is ACTIVE (Vikunja tracking task #$tid, sprint_id $sid per ``docs/active_tasks.yaml``). SDV at ``docs/sprints/sprint_$sid/strategic_design_vision.md``."
    }

    $block = @"
## Active State

- **HEAD reference**: prefer ``git log --oneline main`` over pinning a hash here — the BlarAI main HEAD advances each merge and pinning it in doctrine becomes stale within a sprint.
$sprintBullet
$pytestBullet
- **LEDGER**: per-file (Q1-1 format) in ``docs/ledger/``; monolithic ``docs/POST_OPERATIONAL_MATURATION_LEDGER.md`` frozen at Entry 52.
- **Open issues**: refresh against Vikunja project 3 at each invocation.

(Generated by ``tools/active_state_refresh.ps1`` against HEAD ``$($head.Head)``. Procedure: ``docs/runbooks/active_state_refresh.md``. The Co-Lead pastes this block over the existing §Active State block; do NOT edit in place.)
"@
    return $block
}

# --- Main ---

Write-Host '[active_state_refresh] (a) pytest baseline...' -ForegroundColor Cyan
$pytestResult = if ($SkipPytest) { @{ Passed = 0; Skipped = 0; Raw = '(skipped)' } } else { Get-PytestBaseline }

Write-Host '[active_state_refresh] (b) main HEAD...' -ForegroundColor Cyan
$headResult = Get-MainHead

Write-Host '[active_state_refresh] (c) Vikunja sprint state...' -ForegroundColor Cyan
$vikunjaResult = Get-VikunjaSprintState

Write-Host '[active_state_refresh] (d) active_tasks roster...' -ForegroundColor Cyan
$rosterResult = Get-ActiveRoster

Write-Host '[active_state_refresh] assembling §Active State block...' -ForegroundColor Cyan
$block = Format-ActiveStateBlock -pytest $pytestResult -head $headResult -vikunja $vikunjaResult -roster $rosterResult

Write-Host ''
Write-Host '=== PROSPECTIVE §Active State BLOCK (paste over existing block in CLAUDE.md) ===' -ForegroundColor Green
Write-Host ''
Write-Output $block
Write-Host ''
Write-Host '=== END BLOCK ===' -ForegroundColor Green
exit 0
