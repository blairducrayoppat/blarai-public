#requires -Version 7.2
<#
.SYNOPSIS
  Writes the sanitised summary of the srt-win command-line runs (#1763) for the repository from the raw records in the admin-only output
  root. Read-only on the records; writes one JSON file.

.DESCRIPTION
  Kept: per build, pass and state the srt-win status word, the roles present in S1, srt-win's own `wfp verify` answers, the two host-check
  answers, re-install exit codes and every line srt-win printed about it, restore exit codes, timings, the after-uninstall check results and ACL
  change counts by class, plus the first-cycle run's classified ACL changes. Removed: every machine SID domain (S-1-5-21-a-b-c becomes
  S-1-5-21-<machine>), the operator's user name, every path below the stamped directory in the ACL examples (software inventory), raw stdout/stderr other than srt-win's own lines about each re-install, and the snapshot files.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$StockRecord,
    [Parameter(Mandatory)][string]$PatchedRecord,
    [Parameter(Mandatory)][string]$FirstCycleRecord,
    [Parameter(Mandatory)][string]$FirstCycleOldSnapshot,
    [Parameter(Mandatory)][string]$FirstCycleNewSnapshot,
    [Parameter(Mandatory)][string]$Out
)
$ErrorActionPreference = 'Stop'
$user = [Environment]::UserName

function Hide([string]$s) {
    if ($null -eq $s) { return $null }
    $s = [regex]::Replace($s, 'S-1-5-21-\d+-\d+-\d+', 'S-1-5-21-<machine>')
    if ($user) { $s = [regex]::Replace($s, [regex]::Escape($user), '<user>', 'IgnoreCase') }
    return $s
}

$drv = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'srtcli-halfset.ps1') -Raw
foreach ($n in 'ConvertTo-AceList', 'Get-AclChangeClass') { Invoke-Expression ([regex]::Match($drv, "(?ms)^function $n \{.*?^\}").Value) }
$drvTargets = @([regex]::Matches([regex]::Match($drv, '(?s)\$script:AmbientTargets = @\((.*?)\)\r?\n').Groups[1].Value, "'([^']+)'") | ForEach-Object { $_.Groups[1].Value })
if ($drvTargets.Count -lt 10) { throw "could not read the ambient target list from the driver ($($drvTargets.Count))" }

function Get-BuildSummary([string]$Path) {
    $r = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    [ordered]@{
        build = $r.build; exe_sha256 = $r.exe_sha256; driver_sha256 = $r.driver_sha256; windows_build = $r.windows_build
        started = $r.started; finished = $r.finished; exit = $r.exit; passes_done = $r.passes_done
        acl_baseline = $r.acl_baseline; ambient_stamped_entries = $r.ambient_stamped_entries
        install = @($r.pass_info | ForEach-Object { [ordered]@{ pass = $_.pass; exit = $_.install_exit; ms = $_.install_ms; ambient_paths = @($_.ambient_recorded).Count } })
        export_positive_controls = @($r.export_controls | ForEach-Object { [ordered]@{ pass = $_.pass; srt_win = $_.export.srt_win; s1 = $_.export.s1 } })
        states = @($r.states | ForEach-Object {
            $s = $_
            $o = [ordered]@{ pass = $s.pass; state = $s.state; srt_status = $s.srt_status.state; filters = $s.srt_status.filters; roles_present = @($s.roles_present)
                verify_v4_out = $s.verify_v4_out.probe; verify_v6_out = $s.verify_v6_out.probe
                host_check_stock_ts = $(if ($s.ts_stock.ok) { 'pass' } else { [string]$s.ts_stock.code })
                host_check_patched_ts = $(if ($s.ts_patched.ok) { 'pass' } else { [string]$s.ts_patched.code }) }
            if ($s.PSObject.Properties['verify_v4_in_range']) { $o.verify_v4_in_range = $s.verify_v4_in_range.probe; $o.verify_v6_in_range = $s.verify_v6_in_range.probe }
            $o
        })
        reinstalls = @($r.reinstalls | ForEach-Object { [ordered]@{ pass = $_.pass; state = $_.state; exit = $_.exit; ms = $_.ms; srt_win_said = (Hide ((@(([string]$_.stderr) -split "`r?`n" | Where-Object { $_ -match 'srt-win:' })) -join ' / ')) } })
        restores_force = @($r.restores | ForEach-Object { [ordered]@{ pass = $_.pass; state = $_.state; exit = $_.exit; ms = $_.ms } })
        after_uninstall = @($r.after_uninstall | ForEach-Object {
            [ordered]@{ pass = $_.pass; clean = $_.clean; uninstall_exit = $_.uninstall_exit; uninstall_ms = $_.uninstall_ms; footprint = $_.footprint
                enum_counts_s1_s2_s3 = @($_.enum_counts.PSObject.Properties | ForEach-Object Value); sweep_count = $_.sweep_count
                wfp_state_export = $_.export; user_rights_sid_hits = $_.user_rights_sid_hits; store_dir_sddl = (Hide $_.store_dir_sddl)
                acl = [ordered]@{ entries = $_.acl.entries; sid_hits = $_.acl.sid_hits; changed = $_.acl.changed; equivalent = $_.acl.equivalent; narrowed = $_.acl.narrowed; other = $_.acl.other } }
        })
        operator_controls = [ordered]@{ states = @($r.operator).Count; outside_failures = @($r.operator | Where-Object { -not $_.outside.ok }).Count
            loopback_failures = @($r.operator | Where-Object { -not $_.loopback_v4.ok -or -not $_.loopback_v6.ok }).Count }
    }
}

# First cycle: the run that stopped on its ACL check; its changes classified from the pre-run scratch snapshot.
$fc = Get-Content -LiteralPath $FirstCycleRecord -Raw | ConvertFrom-Json
$load = { param($f) $h = @{}; foreach ($l in [IO.File]::ReadLines($f)) { $i = $l.IndexOf("`t"); if ($i -gt 0) { $h[$l.Substring(0, $i)] = $l.Substring($i + 1) } }; $h }
$A = & $load $FirstCycleOldSnapshot; $B = & $load $FirstCycleNewSnapshot
$classes = [ordered]@{ equivalent = 0; narrowed = 0; other = 0 }; $kinds = [ordered]@{}; $examples = [ordered]@{}
# Sorted, so the example kept per kind (the first path in ordinal order) and the output bytes are the same on every run.
$sortedKeys = [string[]]@($A.Keys); [Array]::Sort($sortedKeys, [StringComparer]::Ordinal)
foreach ($k in $sortedKeys) {
    if (-not $B.ContainsKey($k) -or $A[$k] -ceq $B[$k]) { continue }
    $c = Get-AclChangeClass $A[$k] $B[$k]; $classes[$c]++
    $of = ($A[$k] -replace '^D:', '' -replace '\(.*$', ''); $nf = ($B[$k] -replace '^D:', '' -replace '\(.*$', '')
    $kind = if ($c -eq 'narrowed') { 'allow ACEs removed (re-derived from the parent)' } elseif ($of -ne $nf -and (($A[$k] -replace '^D:[A-Z]*', '') -ceq ($B[$k] -replace '^D:[A-Z]*', ''))) { "DACL flags $(if ($of) { $of } else { '(none)' }) -> $nf, ACEs identical" } elseif ($c -eq 'equivalent') { 'CREATOR OWNER ACE canonicalised' } else { 'other' }
    $kinds[$kind] = 1 + [int]$kinds[$kind]
    # Paths are cut to the stamped directory plus the entry's kind: the names below it are this machine's software inventory.
    $root = @($drvTargets | Where-Object { $k.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) } | Sort-Object Length -Descending | Select-Object -First 1)
    $short = if ($root.Count) { $root[0] + '\...\(' + $(if ([IO.Path]::HasExtension($k)) { 'file ' + [IO.Path]::GetExtension($k) } else { 'folder' }) + ')' } else { '(path withheld)' }
    if (-not $examples.Contains($kind)) { $examples[$kind] = [ordered]@{ path = $short; old = (Hide $A[$k]); new = (Hide $B[$k]) } }
}

$doc = [ordered]@{
    schema = 'nep5-1763-srtcli-summary-v1'
    what = "srt-win's own command line (install, wfp status, wfp verify, install again, install --force, uninstall) against half-sets in a test sublayer, stock and patched builds"
    srt_win_pin = 'anthropics/sandbox-runtime 24eb39e94a6de386e83d126c52317d8e0fa49522'
    sublayer = 'c971a69f-d6ab-4885-9b49-506d8aa51c86 (test sublayer S1; srt-win default sublayer never used)'
    states = [ordered]@{ F = 'full set as installed'; H6 = 'IPv6 block filter deleted'; H4 = 'IPv4 block filter deleted'; HP = 'both loopback permit filters deleted'
        '<state>-after-reinstall' = 'the same state after a plain `srt-win install` with the same arguments' }
    probes = 'wfp verify targets: a 127.0.0.1 and a [::1] listener on an ephemeral port outside 60080-60089; in-range controls on 60085 in F and HP. Host check = verifyWindowsWfpEgress from the stock and the patched TypeScript build, pointed at the build under test.'
    not_measured = @('real IPv6 or internet egress', 'another machine or Windows build', 'a restart with a half-set in place', 'a non-elevated run of the host checks (status needs elevation; verify does not)', 'the patched status-type change through checkWindowsDependencies (only verifyWindowsWfpEgress was driven)', 'file ownership (only the access section of each DACL was snapshotted)')
    builds = @((Get-BuildSummary $StockRecord), (Get-BuildSummary $PatchedRecord))
    first_cycle = [ordered]@{
        note = 'the first live stock pass (driver 819b4d9a) completed every state with the same results as the counted runs, then stopped on its ACL check; not counted in the 3-pass results'
        started = $fc.started; exit = $fc.exit; stop_class = $fc.stop.class
        acl_changes_vs_prerun_snapshot = $classes; kinds = $kinds; example_per_kind = $examples
        later_cycles = 'install/uninstall cycles 2 to 7 (both counted runs) changed no access list'
    }
}
# LF line endings: the bytes (and sha256) recorded in runs/AS_RUN.md are the bytes git stores.
[IO.File]::WriteAllText($Out, ((($doc | ConvertTo-Json -Depth 12) -replace "`r`n", "`n") + "`n"), [Text.UTF8Encoding]::new($false))
$t = Get-Content -LiteralPath $Out -Raw
if ($t -match 'S-1-5-21-\d+-\d+-\d+' -or ($user -and $t -match [regex]::Escape($user))) { throw 'sanitisation failed: a machine SID or the user name is still in the output' }
"written $Out ($((Get-Item -LiteralPath $Out).Length) bytes)"
