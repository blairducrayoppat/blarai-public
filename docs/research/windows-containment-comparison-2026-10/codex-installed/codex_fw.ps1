# Read-only: firewall rules that name the Codex sandbox accounts, and the accounts' group membership.
$sids = @{}
foreach ($n in 'CodexSandboxOffline', 'CodexSandboxOnline') { $sids[$n] = (Get-LocalUser $n).SID.Value }
foreach ($r in Get-NetFirewallRule -ErrorAction SilentlyContinue) {
    $sf = $r | Get-NetFirewallSecurityFilter
    foreach ($n in $sids.Keys) {
        if ($sf.LocalUser -and $sf.LocalUser.Contains($sids[$n])) {
            $pf = $r | Get-NetFirewallPortFilter
            $af = $r | Get-NetFirewallAddressFilter
            '{0} | {1} | {2} {3} | enabled={4} | remote={5} ports={6} | LocalUser={7}' -f $n, $r.DisplayName, $r.Direction, $r.Action, $r.Enabled, ($af.RemoteAddress -join ','), ($pf.RemotePort -join ','), $sf.LocalUser
        }
    }
}
foreach ($g in Get-LocalGroup) {
    $m = @(Get-LocalGroupMember $g -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'CodexSandbox' })
    if ($m.Count) { 'group {0}: {1}' -f $g.Name, (($m | ForEach-Object Name) -join ', ') }
}
