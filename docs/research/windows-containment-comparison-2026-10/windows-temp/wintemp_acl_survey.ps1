# Read-only: classify every object under C:\Windows\Temp by access-list shape, to date the lock.
$all = Get-ChildItem C:/Windows/Temp -Force -Recurse -ErrorAction SilentlyContinue
$locked = [System.Collections.Generic.List[object]]::new()
$inherited = [System.Collections.Generic.List[object]]::new()
$other = [System.Collections.Generic.List[object]]::new()
foreach ($x in $all) {
    $s = (Get-Acl -LiteralPath $x.FullName -ErrorAction SilentlyContinue).Sddl
    if ($null -eq $s) { continue }
    $dacl = $s.Substring($s.IndexOf('D:'))
    if ($dacl -match '^D:PAI?(\(A;(OICI)?;FA;;;SY\)\(A;(OICI)?;FA;;;BA\))$') { $locked.Add($x) }
    elseif ($dacl.Contains(';ID;')) { $inherited.Add($x) }
    else { $other.Add($x) }
}
"objects: $($all.Count)  locked-shape: $($locked.Count)  inherited: $($inherited.Count)  other: $($other.Count)"
if ($locked.Count) { 'locked newest creation: {0:yyyy-MM-dd HH:mm:ss}' -f ($locked | Sort-Object CreationTime | Select-Object -Last 1).CreationTime }
if ($inherited.Count) { 'inherited oldest creation: {0:yyyy-MM-dd HH:mm:ss}' -f ($inherited | Sort-Object CreationTime | Select-Object -First 1).CreationTime }
$other | Select-Object -First 3 | ForEach-Object { 'other: {0} {1}' -f $_.Name, ((Get-Acl -LiteralPath $_.FullName).Sddl -replace 'S-1-5-21-[\d-]+', '<user>') }
$cut = [datetime]'2026-10-08 21:59:23'
$after = $inherited | Where-Object { $_.CreationTime -gt $cut } | Sort-Object CreationTime
'inherited created after the newest locked object: {0}; earliest {1:yyyy-MM-dd HH:mm:ss}' -f @($after).Count, (@($after)[0]).CreationTime
$before = $inherited | Where-Object { $_.CreationTime -le $cut }
'inherited created before it: {0} (sample parent folders: {1})' -f @($before).Count, ((@($before) | ForEach-Object { Split-Path $_.FullName -Parent } | Sort-Object -Unique | Select-Object -First 3) -join ', ')
