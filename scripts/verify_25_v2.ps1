# Item 2.5.v2 functional verification probe.
# For each PS1: extract ONLY the primary RepoRoot/BlarAIRoot ParameterAst (full extent
# including [Alias()] and [string] attributes plus default expression), then build a
# minimal single-param probe scriptblock. This isolates env-fallback / alias / explicit
# precedence semantics without dragging mandatory peer params (Role, Branch, etc.) along.
# For agents-cadence-monitor + la_merge_approve, also evaluate the McpConfigPath
# derivation by appending the body assignment to the probe.

$ErrorActionPreference = 'Stop'

$Scripts = @(
    @{ Path = 'tools/scheduled-tasks/wake_launcher.ps1';            Primary = 'RepoRoot';    HasMcp = $false },
    @{ Path = 'tools/scheduled-tasks/agents-cadence-monitor.ps1';   Primary = 'RepoRoot';    HasMcp = $true  },
    @{ Path = 'tools/scheduled-tasks/escalation_watchdog.ps1';      Primary = 'RepoRoot';    HasMcp = $false },
    @{ Path = 'tools/scheduled-tasks/toast_watchdog.ps1';           Primary = 'RepoRoot';    HasMcp = $false },
    @{ Path = 'tools/scheduled-tasks/la_merge_approve.ps1';         Primary = 'RepoRoot';    HasMcp = $true  },
    @{ Path = 'tools/scheduled-tasks/test_async_post_gate.ps1';     Primary = 'BlarAIRoot';  HasMcp = $false }
)

$Hardcoded = 'C:\Users\mrbla\BlarAI'
$EnvVal    = 'C:\test\envroot'
$ExplicitX = 'C:\explicit'
$ExplicitMcp = 'C:\test'

$results = @()

foreach ($s in $Scripts) {
    $full = Join-Path (Get-Location) $s.Path
    $errors = $null; $tokens = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "Parse errors in $($s.Path): $($errors -join '; ')" }

    $paramBlock = $ast.ParamBlock
    if (-not $paramBlock) { throw "No top-level param block in $($s.Path)" }
    $primary = $s.Primary
    $primaryParam = $paramBlock.Parameters | Where-Object { $_.Name.VariablePath.UserPath -eq $primary } | Select-Object -First 1
    if (-not $primaryParam) { throw "Primary param `$$primary not found in $($s.Path)" }

    $paramText = $primaryParam.Extent.Text

    if ($s.HasMcp) {
        $bodyEmit = "`$McpConfigPath = Join-Path `$$primary '.mcp.json'; [pscustomobject]@{ Primary = `$$primary; McpConfigPath = `$McpConfigPath }"
    } else {
        $bodyEmit = "[pscustomobject]@{ Primary = `$$primary }"
    }
    $sbText = "param( $paramText )`n$bodyEmit"
    $sb = [scriptblock]::Create($sbText)

    Remove-Item Env:BLARAI_ROOT -ErrorAction SilentlyContinue
    $r1 = & $sb
    $axis1 = ($r1.Primary -eq $Hardcoded)

    $env:BLARAI_ROOT = $EnvVal
    $r2 = & $sb
    $axis2 = ($r2.Primary -eq $EnvVal)
    Remove-Item Env:BLARAI_ROOT

    $r3 = & $sb -BlarAIRoot $ExplicitX
    $axis3 = ($r3.Primary -eq $ExplicitX)

    $axis4 = $null; $axis4Val = $null
    if ($s.HasMcp) {
        $r4 = & $sb -BlarAIRoot $ExplicitMcp
        $expected = Join-Path $ExplicitMcp '.mcp.json'
        $axis4Val = $r4.McpConfigPath
        $axis4 = ($r4.McpConfigPath -eq $expected)
    }

    $results += [pscustomobject]@{
        Script  = Split-Path $s.Path -Leaf
        Primary = $primary
        Axis1_Baseline      = if ($axis1) { 'PASS' } else { "FAIL ($($r1.Primary))" }
        Axis2_EnvFallback   = if ($axis2) { 'PASS' } else { "FAIL ($($r2.Primary))" }
        Axis3_AliasBinding  = if ($axis3) { 'PASS' } else { "FAIL ($($r3.Primary))" }
        Axis4_McpDerivation = if ($null -eq $axis4) { 'N/A' } elseif ($axis4) { 'PASS' } else { "FAIL ($axis4Val)" }
    }
}

$results | Format-Table -AutoSize

$failCount = ($results | Where-Object {
    $_.Axis1_Baseline -ne 'PASS' -or
    $_.Axis2_EnvFallback -ne 'PASS' -or
    $_.Axis3_AliasBinding -ne 'PASS' -or
    ($_.Axis4_McpDerivation -ne 'PASS' -and $_.Axis4_McpDerivation -ne 'N/A')
}).Count

Write-Host ""
if ($failCount -eq 0) {
    Write-Host "ALL_GREEN: 6 scripts x 3 axes (18) + 2 scripts x McpConfigPath axis (2) = 20 checks PASS"
} else {
    Write-Host "FAILURES: $failCount scripts have at least one axis failure"
    exit 1
}
