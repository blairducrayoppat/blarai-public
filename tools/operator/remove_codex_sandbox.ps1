#requires -Version 7.0
<#
.SYNOPSIS
  Removes the OpenAI Codex sandbox leftovers from this machine, and nothing else.
  For the Lead Architect to run (double-click remove_codex_sandbox.cmd).

.DESCRIPTION
  What it removes (each by EXACT name or SID, listed in Get-RealSpec):
    Stage Accounts (the default):
      * the local accounts CodexSandboxOffline and CodexSandboxOnline (disabled first, deleted last)
        and the group CodexSandboxUsers
      * the firewall rules codex_sandbox_offline_block_loopback_tcp and ..._udp
      * the two hidden-user values under HKLM Winlogon SpecialAccounts UserList
    Stage AclEntries:
      * the entries naming the three Codex capability SIDs in the access lists of the objects under
        the BlarAI folder (and its .git deny entries), the user Temp folder and C:\ovms. Only those
        entries are cut out of each object's own list; every other entry stays as it is.
  What it does not touch:
    * anything under C:\Users\mrbla\.codex (listed, never changed)
    * any account, group, rule, task, service or value not named above
    * other entries in the same registry key or the same access lists
  If it finds anything unexpected (a different SID for a named account, a profile, a logon record,
  an extra group member or an extra group of an account, extra Codex-named rules, tasks or services,
  Windows Filtering Platform filters, user-rights assignments) it changes nothing and says why.

  Stages (-Stage, any letter case, default Accounts; anything else exits 2 and changes nothing):
    Accounts     the account, rule and value steps above. Complete on its own: its own plan digest,
                 backup and undo note, verification. It reads and writes no access list and takes no
                 snapshot of one.
    AclEntries   the access-entry steps. Refused for -Apply and -Guided on the real machine until its
                 review findings are closed.
    All          both in one run (same refusal on the real machine).

  Modes (default is -DryRun, which changes nothing):
    -DryRun                      print the plan, current state versus target, and its digest
    -Apply -ExpectPlan <digest>  apply only the plan whose digest the dry run printed
    -Guided                      dry run, then ask for the word APPLY, then apply
    -Verify                      read-only check that the end state holds
    -RestoreAcl <folder>         put recorded access lists back exactly (refused on the real machine)
    -SelfTest                    needs an elevated shell and about 15 minutes; creates and removes its own
                                 throwaway zz1740-<token>-* accounts, rules, registry keys and folders
                                 under C:\blarai-spike-1740-ops and never changes a real Codex object

  Order, stage Accounts: both accounts are DISABLED first (reversible, so a stop part-way never leaves
  a usable Codex account behind), then the firewall rules, the hidden-user values, and last the
  irreversible deletion of the accounts and the group. Stage AclEntries / All: the access lists first,
  then a read-back of every object, and only if that finds nothing wrong the account steps. A stop
  before the irreversible steps leaves them untouched, and the apply can be run again.

  Undo: a backup folder is written before any change, SYSTEM and Administrators only (default
  C:\ProgramData\blarai-operator\backups\remove-codex-<time>-<token>). It holds backup.json (full
  prior state) and undo-commands.txt; for the access-entry stage also tree-snapshot.tsv (the access
  list of every object under the three folders) with its hash. Firewall rules and registry values
  are recreatable from the undo note, an account that was only disabled can be re-enabled, and the
  access lists come back exactly with -RestoreAcl. Deleted accounts and the group are NOT recoverable
  (a recreated account gets a new SID). A re-run after a stop lists already-removed items as gone;
  the undo note names the earlier folders that hold them.

  Running Codex again is not blocked by this script: its elevated setup recreates the accounts,
  rules and access entries, and with ~/.codex/cap_sid kept it reuses the same capability SIDs.
  Delete cap_sid (and auth.json) afterwards if that is not wanted.

  Recorded account and group SIDs: since 2026-10-13 (#1765) the SIDs in Get-RealSpec for CodexSandboxOffline,
  CodexSandboxOnline and CodexSandboxUsers carry a placeholder domain, not this machine's. The real ones belonged
  to objects deleted on 2026-10-11 (Stage 1, #1743) and cannot recur. Stage Accounts therefore refuses at
  'sid-match' for any account that carries one of those names (fail-closed: a recreated Codex account is a
  different identity and this script does not remove it). The scans that looked for those three identities by SID
  (access lists, Windows Filtering Platform filters, scheduled tasks, user rights) are BLIND to any residue of the
  deleted objects: such residue carries only the SID (a deleted account has no name to match), so a -Verify that
  reports no leftover for them is not evidence that none exists. The name-based needles (CodexSandbox* in tasks,
  rights and firewall rules) still run, and Stage AclEntries looks for Codex's capability SIDs, which are unchanged.

  The access-entry stage edits each object's OWN list: it is opened once, its list read, the Codex
  entries cut out of that exact list, and the list written back through the same handle with the
  kernel call itself (order, inherited flags and protection kept). Windows is never asked to
  recompute or re-propagate anything, so no other principal gains or loses access, stale inherited
  entries stay, and no inheritance setting changes. Every object is recorded first and read back
  afterwards; any other difference stops the run before the irreversible steps.

  A check that cannot run refuses the apply (exit 2) and is never skipped: the Windows Filtering
  Platform and user-rights exports must produce a recognisable file, and a failed read is never
  taken for "already gone".

  Run path: the double-click launcher copies this script to the protected folder
  C:\ProgramData\blarai-operator\run-1743 and runs the copy. It prints the script's SHA-256
  (over LF-normalised bytes, so line endings do not change it) before and after the copy; the plan
  digest includes that hash. The hash check catches a file that changed after the launcher read it;
  it does not protect against a deliberate swap before that, and a tampered launcher is trusted.

  Exit codes: 0 pass, 1 verify/post-check FAIL, 2 refused before any change (also a mistyped
  -Stage), 3 stopped part-way (earlier steps done, later steps untouched).
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Apply,
    [string]$ExpectPlan,
    [switch]$Verify,
    [switch]$Guided,
    [switch]$SelfTest,
    [switch]$HoldOpen,
    [string]$ExpectScriptSha256,
    [string]$ResumeFrom = '',
    [string]$RestoreAcl = '',
    [string]$RestorePath = '',
    [string]$Stage = 'Accounts',
    [string]$BackupRoot = (Join-Path $env:ProgramData 'blarai-operator\backups'),
    [int]$ScanSeconds = 1800,
    [int]$SnapshotSeconds = 1800
)
$ErrorActionPreference = 'Stop'
# The parameter accepts any letter case; everything below uses the canonical spelling.
$Stage = switch ("$Stage".ToLowerInvariant()) { 'accounts' { 'Accounts' } 'aclentries' { 'AclEntries' } 'all' { 'All' } default { $Stage } }
$script:SelfPath = $PSCommandPath
$script:SelfTestActive = $false
$script:SimulateOnly = $false
$script:GatesOff = @()
$script:SimLog = [System.Collections.Generic.List[string]]::new()
$script:BackupTamper = $null
$script:StepFault = $null
$script:ExportFault = $null
$script:ReadFault = $null
$script:AdminTempRoot = Join-Path $env:ProgramData 'blarai-operator'
$script:ProgressOn = $false
$script:AclRemovalSeconds = 1800
$script:WalkHook = $null
$script:WriteFault = $null
$script:AfterRemovalHook = $null
$script:LastRemoval = $null
$script:ThrowRoot = 'C:\blarai-spike-1740-ops'
$script:Pfx = 'zz1740-'
$script:Own = 'zz1740-'
# Digest of Get-RealSpec; a spec labelled real that does not hash to this is refused.
# Re-pinned 2026-10-13 (#1765) after the account and group SIDs in Get-RealSpec were rewritten to the placeholder domain
# S-1-5-21-1000000001-1000000002-1000000003 (relative ids 1006-1008 kept). Those accounts and the group were deleted by the
# Stage 1 apply of 2026-10-11 (#1743 comment 4058); a deleted account's SID never recurs, so no live object can match the
# recorded SIDs again. Effect on the gates: 'sid-match' refuses any account or group that carries one of the recorded names,
# which is the closed direction; the scans that look for the recorded account and group SIDs in access lists, filters,
# tasks and rights (Get-ScanSids, Find-RightsHits, the WFP export) can no longer find the deleted identities' real SIDs,
# and residue of a deleted object carries only the SID, so for those three identities these scans are blind (the name
# needles still match live names). The capability SIDs (cap, ExtraScanSids) are Codex's own, not this machine's, and
# are unchanged. The real machine domain is kept out of this repository by tests/security/test_no_machine_sid_domain_in_tree.py.
$script:RealSpecPin = '8101e3215b86a5dbf12ad6d88d64b3893e8257ba914c64e8407a67a000bab951'

# ---------------------------------------------------------------- locks and gates

function Refuse([string]$Gate, [string]$Msg) {
    throw [System.InvalidOperationException]::new("REFUSED[$Gate]: $Msg")
}
# A gate is enforced unless the self-test has switched it off for a mutation probe.
function Test-Gate([string]$Gate) {
    if ($script:SelfTestActive -and ($script:GatesOff -contains $Gate)) { return $false }
    return $true
}
# Every destructive cmdlet runs through here; the self-test can simulate instead of act.
function Invoke-Destructive([string]$Kind, [string]$Target, [scriptblock]$Do) {
    if ($script:SimulateOnly) { $script:SimLog.Add("$Kind|$Target"); return }
    & $Do
}
function Test-Elevated { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
function Assert-Elevated([bool]$IsAdmin) {
    if ((Test-Gate 'elevation') -and -not $IsAdmin) { Refuse 'elevation' 'this must run as administrator' }
}

# ---------------------------------------------------------------- the allowlist

function Get-RealSpec {
    $cap = [ordered]@{
        workspace = 'S-1-5-21-2312800277-2850374765-3180428357-3295445259'
        cwd       = 'S-1-5-21-76345465-2051216645-4251589009-2931813655'
    }
    [ordered]@{
        Mode              = 'real'
        Users             = @(
            [ordered]@{ Name = 'CodexSandboxOffline'; Sid = 'S-1-5-21-1000000001-1000000002-1000000003-1007' },
            [ordered]@{ Name = 'CodexSandboxOnline'; Sid = 'S-1-5-21-1000000001-1000000002-1000000003-1008' })
        Group             = [ordered]@{ Name = 'CodexSandboxUsers'; Sid = 'S-1-5-21-1000000001-1000000002-1000000003-1006'; Description = 'Codex sandbox internal group (managed)' }
        Firewall          = @(
            [ordered]@{ DisplayName = 'codex_sandbox_offline_block_loopback_tcp'; Name = '{CC8B9C8F-6DB1-4A6C-A230-902644BD579A}'; UserSid = 'S-1-5-21-1000000001-1000000002-1000000003-1007' },
            [ordered]@{ DisplayName = 'codex_sandbox_offline_block_loopback_udp'; Name = '{B20BC261-E697-44FC-9D27-510CF4C09776}'; UserSid = 'S-1-5-21-1000000001-1000000002-1000000003-1007' })
        FirewallGlob      = 'codex*'
        ServiceGlob       = 'codex'
        Registry          = [ordered]@{ Path = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList'; Names = @('CodexSandboxOffline', 'CodexSandboxOnline') }
        ProfileListRoot   = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
        ProfileFolderRoot = 'C:\Users'
        WfpNeedles        = @('codex', '2e31d31c', 'e65054fd')
        ExtraScanSids     = @('S-1-5-21-2620682446-2269186101-2640295642-4053466963')
        # LA decision 2026-10-11: a hard-linked file under the access-entry folders may have other names under this folder (its subtree only); the file's list is shared, so it is edited once for all names
        LinkRoots         = @('C:\Users\mrbla\blarai-wt-1616-accuracy\models')
        AclTargets        = @(
            [ordered]@{ Id = 'A8'; Path = 'C:\Users\mrbla\BlarAI\.git'; Sid = $cap.workspace; Scan = $false },
            [ordered]@{ Id = 'A7'; Path = 'C:\Users\mrbla\BlarAI'; Sid = $cap.cwd; Scan = $true },
            [ordered]@{ Id = 'A9'; Path = 'C:\Users\mrbla\AppData\Local\Temp'; Sid = $cap.workspace; Scan = $true },
            [ordered]@{ Id = 'A10'; Path = 'C:\ovms'; Sid = $cap.workspace; Scan = $true })
        ReportOnly        = 'C:\Users\mrbla\.codex'
    }
}

function Copy-Spec($Spec) {
    $c = [ordered]@{}
    foreach ($k in $Spec.Keys) { $c[$k] = $Spec[$k] }
    return $c
}
function Get-SpecDigest($Spec) {
    $json = $Spec | ConvertTo-Json -Depth 8 -Compress
    $h = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($json))
    return ([BitConverter]::ToString($h) -replace '-', '').ToLowerInvariant()
}

function Test-UnderThrowRoot([string]$Path) {
    try { $full = [IO.Path]::GetFullPath($Path) } catch { return $false }
    return $full.StartsWith("$($script:ThrowRoot)\$($script:Pfx)", [StringComparison]::OrdinalIgnoreCase)
}

function Assert-ThrowawaySpec($Spec) {
    $bad = [System.Collections.Generic.List[string]]::new()
    $pf = $script:Pfx
    $chk = { param($v, $what) if (-not ([string]$v).StartsWith($pf, [StringComparison]::Ordinal)) { $bad.Add("$what '$v'") } }
    foreach ($u in $Spec.Users) { & $chk $u.Name 'user' }
    & $chk $Spec.Group.Name 'group'
    foreach ($f in $Spec.Firewall) { & $chk $f.DisplayName 'rule'; & $chk $f.Name 'rule id' }
    & $chk $Spec.FirewallGlob 'rule glob'
    & $chk $Spec.ServiceGlob 'service glob'
    foreach ($n in $Spec.Registry.Names) { & $chk $n 'registry value' }
    if (-not $Spec.Registry.Path.StartsWith('HKCU:\Software\zz1740-', [StringComparison]::OrdinalIgnoreCase)) { $bad.Add("registry path '$($Spec.Registry.Path)'") }
    if (-not $Spec.ProfileListRoot.StartsWith('HKCU:\Software\zz1740-', [StringComparison]::OrdinalIgnoreCase)) { $bad.Add("profile list '$($Spec.ProfileListRoot)'") }
    foreach ($p in @($Spec.ProfileFolderRoot, $Spec.ReportOnly) + @($Spec.LinkRoots | Where-Object { $_ }) + @($Spec.AclTargets | ForEach-Object { $_.Path })) {
        if (-not (Test-UnderThrowRoot $p)) { $bad.Add("path '$p'") }
    }
    if ($bad.Count) { Refuse 'spec-throwaway' ("test mode accepts only zz1740-* objects under $($script:ThrowRoot); not allowed: " + ($bad -join '; ')) }
}

function Assert-NoWildcard([string]$Name, [string]$What) {
    if ($Name -match '[\*\?\[\]]') { Refuse 'spec-wildcard' "$What '$Name' contains a wildcard; names are matched exactly" }
}

# Called by every destructive helper at the point of action.
function Assert-SpecAllowed($Spec) {
    foreach ($n in @($Spec.Users | ForEach-Object { $_.Name }) + $Spec.Group.Name + @($Spec.Firewall | ForEach-Object { $_.DisplayName }) + $Spec.Registry.Names) { Assert-NoWildcard $n 'name' }
    if ($Spec.Mode -ceq 'real') {
        if ((Test-Gate 'spec-real-pinned') -and ((Get-SpecDigest $Spec) -cne $script:RealSpecPin)) {
            Refuse 'spec-real-pinned' 'the allowlist is not the built-in real allowlist'
        }
        if ($script:SelfTestActive -and (Test-Gate 'selftest-no-real')) {
            Refuse 'selftest-no-real' 'the self-test never acts on the real allowlist'
        }
    } elseif ($Spec.Mode -ceq 'test') {
        if (Test-Gate 'spec-throwaway') { Assert-ThrowawaySpec $Spec }
    } else { Refuse 'spec-mode' "unknown spec mode '$($Spec.Mode)'" }
}

# ---------------------------------------------------------------- pure helpers

# Whole SIDs found in a descriptor string; '-1007' never matches '-10070'.
function Get-SddlSids([string]$Text) {
    return @([regex]::Matches($Text, 'S-1-\d+(?:-\d+)+') | ForEach-Object { $_.Value } | Sort-Object -Unique)
}
# True only when the scope names exactly the one SID.
function Test-ScopeOnlySid([string]$LocalUser, [string]$Sid) {
    # every entry of any type and any principal form (full SID or a shorthand such as WD or BU) counts
    $aces = @(Get-AceInfo $LocalUser)
    return ($aces.Count -eq 1) -and ($aces[0].Type -ceq 'A') -and ($aces[0].Sid -ceq $Sid)
}

function Get-PurgeSids($Spec) { return @($Spec.AclTargets | ForEach-Object { $_.Sid } | Select-Object -Unique) }
# SIDs the deep scans look for: the purged ones plus the other Codex capability SID and the
# recorded SIDs of the accounts and group (placeholders since 2026-10-13, see RealSpecPin: they
# cannot match residue of the deleted objects). Entries for the last two groups are never
# removed, so the apply refuses to start when it finds one.
function Get-ScanSids($Spec) {
    $all = @(Get-PurgeSids $Spec)
    if (Test-Gate 'scan-all-sids') { $all += @($Spec.ExtraScanSids) + @($Spec.Users | ForEach-Object { $_.Sid }) + $Spec.Group.Sid }
    return @($all | Where-Object { $_ } | Select-Object -Unique)
}
# secedit lists local accounts by NAME and only well-known or domain principals by SID, so
# both the SIDs and the names are looked for (the recorded account SIDs are placeholders, so
# only the names can hit for the deleted accounts).
function Find-RightsHits($Spec, [string]$Text) {
    $needles = @(@($Spec.Users | ForEach-Object { $_.Sid }) + $Spec.Group.Sid)
    if (Test-Gate 'rights-by-name') { $needles += @($Spec.Users | ForEach-Object { $_.Name }) + $Spec.Group.Name + @($Spec.WfpNeedles) }
    return @($needles | Where-Object { $_ -and $Text.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 } | Select-Object -Unique)
}
# Keys of an access list, ignoring the inherited bit, with the dropped SIDs removed.
function ConvertTo-AceKeys([string]$Sddl, [string[]]$DropSids) {
    $sd = [Security.AccessControl.RawSecurityDescriptor]::new($Sddl)
    $keys = foreach ($a in $sd.DiscretionaryAcl) {
        $sid = $a.SecurityIdentifier.Value
        if ($DropSids -contains $sid) { continue }
        '{0}|{1}|{2}|{3}' -f $a.AceType, ([int]$a.AceFlags -band (-bnot 0x10)), $a.AccessMask, $sid
    }
    return @($keys | Sort-Object)
}

# $null when the only difference between the two access lists is the dropped SIDs.
function Get-AceDelta([string]$Old, [string]$New, [string[]]$DropSids) {
    try {
        $o = @(ConvertTo-AceKeys $Old $DropSids); $n = @(ConvertTo-AceKeys $New @())
        $lost = @($o | Where-Object { $n -cnotcontains $_ }); $gained = @($n | Where-Object { $o -cnotcontains $_ })
        if (-not $lost.Count -and -not $gained.Count) { return $null }
        return "lost=[$($lost -join ' ')] gained=[$($gained -join ' ')]"
    } catch { return "unparseable access list: $($_.Exception.Message)" }
}

# ---- native helpers (compiled on first use)
$script:OpNativeSource = @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class OpNet {
    [StructLayout(LayoutKind.Sequential)] struct LGMI0 { public IntPtr sid; }
    [DllImport("netapi32.dll", CharSet = CharSet.Unicode)] static extern int NetLocalGroupGetMembers(string server, string group, int level, out IntPtr buf, int maxlen, out int read, out int total, ref IntPtr resume);
    [DllImport("netapi32.dll")] static extern int NetApiBufferFree(IntPtr buf);
    // Member SIDs of a local group, including members whose account no longer exists.
    public static string[] GroupMemberSids(string group) {
        IntPtr buf; int read; int total; IntPtr resume = IntPtr.Zero;
        int rc = NetLocalGroupGetMembers(null, group, 0, out buf, -1, out read, out total, ref resume);
        if (rc != 0) throw new System.ComponentModel.Win32Exception(rc);
        try {
            var res = new string[read];
            int sz = Marshal.SizeOf(typeof(LGMI0));
            for (int i = 0; i < read; i++) {
                var m = (LGMI0)Marshal.PtrToStructure(IntPtr.Add(buf, i * sz), typeof(LGMI0));
                res[i] = new System.Security.Principal.SecurityIdentifier(m.sid).Value;
            }
            return res;
        } finally { NetApiBufferFree(buf); }
    }
}

public static class OpNetUser {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct LUI0 { [MarshalAs(UnmanagedType.LPWStr)] public string name; }
    [DllImport("netapi32.dll", CharSet = CharSet.Unicode)] static extern int NetUserGetLocalGroups(string server, string user, int level, int flags, out IntPtr buf, int maxlen, out int read, out int total);
    [DllImport("netapi32.dll")] static extern int NetApiBufferFree(IntPtr buf);
    // Names of the local groups an account is a direct member of.
    public static string[] LocalGroups(string user) {
        IntPtr buf; int read; int total;
        int rc = NetUserGetLocalGroups(null, user, 0, 0, out buf, -1, out read, out total);
        if (rc != 0) throw new System.ComponentModel.Win32Exception(rc);
        try {
            var res = new string[read];
            int sz = Marshal.SizeOf(typeof(LUI0));
            for (int i = 0; i < read; i++) res[i] = ((LUI0)Marshal.PtrToStructure(IntPtr.Add(buf, i * sz), typeof(LUI0))).name;
            return res;
        } finally { NetApiBufferFree(buf); }
    }
}

public sealed class OpObjInfo {
    public bool IsDirectory;
    public bool IsReparse;
    public uint Links;
    public uint Attributes;
    public string FinalPath;
}

// Handle-based reads and writes of one object's access list. The object is opened once (a link at the
// leaf is opened as the link itself), what it is gets checked on THAT handle, and the write goes through
// the same handle with the kernel call itself: exactly the list given, no inheritance processing and no
// propagation (SetSecurityInfo and SetNamedSecurityInfo re-derive inherited entries and rewrite the children).
public static class OpAcl {
    const uint READ_CONTROL = 0x20000, WRITE_DAC = 0x40000, FILE_READ_ATTRIBUTES = 0x80;
    const uint FILE_SHARE_READ = 1, FILE_SHARE_WRITE = 2, OPEN_EXISTING = 3;
    const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000, FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
    const uint DACL_SECURITY_INFORMATION = 4;
    const int SE_FILE_OBJECT = 1;

    [StructLayout(LayoutKind.Sequential)]
    struct BY_HANDLE_FILE_INFORMATION {
        public uint dwFileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME ftCreationTime, ftLastAccessTime, ftLastWriteTime;
        public uint dwVolumeSerialNumber, nFileSizeHigh, nFileSizeLow, nNumberOfLinks, nFileIndexHigh, nFileIndexLow;
    }
    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    struct TOKEN_PRIVILEGES { public int Count; public long Luid; public int Attr; }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr sec, uint disp, uint flags, IntPtr tmpl);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetFileInformationByHandle(SafeFileHandle h, out BY_HANDLE_FILE_INFORMATION info);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern uint GetFinalPathNameByHandleW(SafeFileHandle h, StringBuilder buf, uint len, uint flags);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern uint GetSecurityInfo(SafeFileHandle h, int objType, uint info, out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr sd);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool ConvertSecurityDescriptorToStringSecurityDescriptorW(IntPtr sd, uint rev, uint info, out IntPtr str, out uint len);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string s, uint rev, out IntPtr sd, out uint len);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool GetSecurityDescriptorDacl(IntPtr sd, out bool present, out IntPtr dacl, out bool defaulted);
    [DllImport("ntdll.dll")]
    static extern int NtSetSecurityObject(SafeFileHandle h, uint info, IntPtr sd);
    [DllImport("ntdll.dll")]
    static extern uint RtlNtStatusToDosError(int status);
    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr p);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("kernel32.dll")]
    static extern IntPtr GetCurrentProcess();
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool LookupPrivilegeValueW(string system, string name, out long luid);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool AdjustTokenPrivileges(IntPtr token, bool disableAll, ref TOKEN_PRIVILEGES np, int len, IntPtr prev, IntPtr retLen);
    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr FindFirstFileNameW(string file, uint flags, ref uint len, StringBuilder name);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool FindNextFileNameW(IntPtr h, ref uint len, StringBuilder name);
    [DllImport("kernel32.dll")]
    static extern bool FindClose(IntPtr h);

    static string Ext(string path) {
        return path.StartsWith(@"\\?\", StringComparison.Ordinal) ? path : @"\\?\" + path;
    }

    // Lets the elevated token use backup/restore rights so an object's own list cannot lock the operator out.
    public static bool EnablePrivilege(string name) {
        IntPtr tok;
        if (!OpenProcessToken(GetCurrentProcess(), 0x28, out tok)) return false;
        try {
            long luid;
            if (!LookupPrivilegeValueW(null, name, out luid)) return false;
            var tp = new TOKEN_PRIVILEGES { Count = 1, Luid = luid, Attr = 2 };
            AdjustTokenPrivileges(tok, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero);
            return Marshal.GetLastWin32Error() == 0;
        } finally { CloseHandle(tok); }
    }

    // Every name (hard link) of a file, as drive-qualified paths.
    public static string[] LinkNames(string path) {
        var res = new System.Collections.Generic.List<string>();
        string drive = path.Length >= 2 && path[1] == ':' ? path.Substring(0, 2) : "";
        uint len = 1024; var sb = new StringBuilder((int)len);
        IntPtr h = FindFirstFileNameW(Ext(path), 0, ref len, sb);
        if (h == new IntPtr(-1)) {
            int e = Marshal.GetLastWin32Error();
            if (e != 234) throw new System.ComponentModel.Win32Exception(e);
            sb = new StringBuilder((int)len + 2); h = FindFirstFileNameW(Ext(path), 0, ref len, sb);
            if (h == new IntPtr(-1)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        }
        try {
            res.Add(drive + sb.ToString());
            while (true) {
                len = 1024; sb = new StringBuilder((int)len);
                if (!FindNextFileNameW(h, ref len, sb)) {
                    int e = Marshal.GetLastWin32Error();
                    if (e == 234) { sb = new StringBuilder((int)len + 2); if (FindNextFileNameW(h, ref len, sb)) { res.Add(drive + sb.ToString()); continue; } e = Marshal.GetLastWin32Error(); }
                    if (e == 38) break;
                    throw new System.ComponentModel.Win32Exception(e);
                }
                res.Add(drive + sb.ToString());
            }
        } finally { FindClose(h); }
        return res.ToArray();
    }

    public static SafeFileHandle Open(string path) {
        SafeFileHandle h = CreateFileW(Ext(path), READ_CONTROL | WRITE_DAC | FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE,
            IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
        if (h.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "cannot open " + path);
        return h;
    }

    public static OpObjInfo Inspect(SafeFileHandle h) {
        BY_HANDLE_FILE_INFORMATION bi;
        if (!GetFileInformationByHandle(h, out bi)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        var sb = new StringBuilder(1024);
        uint n = GetFinalPathNameByHandleW(h, sb, (uint)sb.Capacity, 0);
        if (n == 0) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if (n >= sb.Capacity) {
            sb = new StringBuilder((int)n + 2);
            n = GetFinalPathNameByHandleW(h, sb, (uint)sb.Capacity, 0);
            if (n == 0) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        }
        return new OpObjInfo {
            Attributes = bi.dwFileAttributes,
            IsDirectory = (bi.dwFileAttributes & 0x10) != 0,
            IsReparse = (bi.dwFileAttributes & 0x400) != 0,
            Links = bi.nNumberOfLinks,
            FinalPath = sb.ToString()
        };
    }

    // The access list exactly as stored (order, inherited flags, protection) as an SDDL string.
    public static string GetSddl(SafeFileHandle h) {
        IntPtr o, g, d, s, sd;
        uint rc = GetSecurityInfo(h, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, out o, out g, out d, out s, out sd);
        if (rc != 0) throw new System.ComponentModel.Win32Exception((int)rc);
        try {
            IntPtr str; uint len;
            if (!ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, DACL_SECURITY_INFORMATION, out str, out len)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            try { return Marshal.PtrToStringUni(str); } finally { LocalFree(str); }
        } finally { LocalFree(sd); }
    }

    public static void SetSddl(SafeFileHandle h, string sddl) {
        IntPtr sd; uint len;
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, out sd, out len)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "bad access list text");
        try {
            bool present, defaulted; IntPtr dacl;
            if (!GetSecurityDescriptorDacl(sd, out present, out dacl, out defaulted) || !present) throw new InvalidOperationException("the text has no access list");
            int st = NtSetSecurityObject(h, DACL_SECURITY_INFORMATION, sd);
            if (st < 0) throw new System.ComponentModel.Win32Exception((int)RtlNtStatusToDosError(st));
        } finally { LocalFree(sd); }
    }
}
'@
function Initialize-OpNative {
    if (-not ('OpAcl' -as [type])) { Add-Type -TypeDefinition $script:OpNativeSource -Language CSharp }
}
# Local groups an existing account belongs to, sorted; 'unreadable' when they cannot be read.
function Get-UserGroupNames([string]$Name) {
    try { Initialize-OpNative; return @([OpNetUser]::LocalGroups($Name) | Sort-Object) } catch { return @('unreadable') }
}
# Member SIDs of a local group, sorted; 'unreadable' when the list cannot be read.
function Get-GroupMemberSids([string]$Name) {
    try { Initialize-OpNative; return @([OpNet]::GroupMemberSids($Name) | Sort-Object) } catch { return @('unreadable') }
}

# ---- protected folders: backups and export scratch are written where ordinary processes cannot alter them
$script:TrustedOwners = @('S-1-5-18', 'S-1-5-32-544', 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')

# Creates the folder already protected (SYSTEM and Administrators only, owned by Administrators) in the one call.
function New-AdminOnlyDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) { throw "'$Path' already exists" }
    $sec = [Security.AccessControl.DirectorySecurity]::new()
    $sec.SetOwner([Security.Principal.SecurityIdentifier]'S-1-5-32-544')
    $sec.SetAccessRuleProtection($true, $false)
    foreach ($id in 'S-1-5-18', 'S-1-5-32-544') {
        $sec.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$id, [Security.AccessControl.FileSystemRights]::FullControl, 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    }
    [void][IO.FileSystemAclExtensions]::Create([IO.DirectoryInfo]::new($Path), $sec)
    Assert-AdminOnlyDirectory $Path
}
# Refuses a folder that is a link, sits below a link, is not protected, is not owned by a trusted owner, or grants anyone else access.
function Assert-AdminOnlyDirectory([string]$Path) {
    if (-not (Test-Gate 'backup-dir-secure')) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Refuse 'backup-dir-secure' "'$Path' is a link" }
    for ($d = $item.Parent; $d; $d = $d.Parent) {
        if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { Refuse 'backup-dir-secure' "'$($d.FullName)' above '$Path' is a link" }
    }
    $acl = [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($Path), [Security.AccessControl.AccessControlSections]'Access,Owner')
    if (-not $acl.AreAccessRulesProtected) { Refuse 'backup-dir-secure' "'$Path' inherits its access list from a folder others can write" }
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($script:TrustedOwners -cnotcontains $owner) { Refuse 'backup-dir-secure' "'$Path' is owned by $owner" }
    foreach ($r in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($r.AccessControlType -eq 'Allow' -and $script:TrustedOwners -cnotcontains $r.IdentityReference.Value) { Refuse 'backup-dir-secure' "'$Path' grants access to $($r.IdentityReference.Value)" }
    }
}
# A fresh scratch folder for the exports, under a protected root.
function New-AdminTempDirectory {
    $root = $script:AdminTempRoot
    if (Test-Path -LiteralPath $root) { Assert-AdminOnlyDirectory $root } else { New-AdminOnlyDirectory $root }
    $d = Join-Path $root ('rcs-' + [guid]::NewGuid().ToString('N'))
    New-AdminOnlyDirectory $d
    return $d
}

# "Not found" is an answer; any other failure to read is thrown, so it can never look like 'already gone'.
function Get-LocalUserOrNull([string]$Name) {
    try { return Get-LocalUser -Name $Name -ErrorAction Stop } catch [Microsoft.PowerShell.Commands.UserNotFoundException] { return $null }
}
function Get-LocalGroupOrNull([string]$Name) {
    try { return Get-LocalGroup -Name $Name -ErrorAction Stop } catch [Microsoft.PowerShell.Commands.GroupNotFoundException] { return $null }
}
function Get-FirewallRulesByDisplayName([string]$Pattern) {
    try { return @(Get-NetFirewallRule -DisplayName $Pattern -ErrorAction Stop) }
    catch {
        if ($_.CategoryInfo.Category -eq 'ObjectNotFound' -or $_.FullyQualifiedErrorId -like '*ObjectNotFound*' -or $_.Exception.Message -like '*No MSFT_NetFirewallRule objects found*') { return @() }
        throw
    }
}

# SHA-256 over the file with CRLF turned into LF, so a checkout with Windows line endings gives the same value.
function Get-NormalisedSha256([string]$Path) {
    $b = [IO.File]::ReadAllBytes($Path)
    $o = [System.Collections.Generic.List[byte]]::new($b.Length)
    for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -eq 13 -and ($i + 1) -lt $b.Length -and $b[$i + 1] -eq 10) { continue }; $o.Add($b[$i]) }
    return ([BitConverter]::ToString([Security.Cryptography.SHA256]::HashData($o.ToArray())) -replace '-', '')
}
# SHA-256 of this very file: part of the plan digest, so a changed script cannot approve itself with an old digest.
$script:ScriptShaOverride = $null
$script:ScriptShaCache = $null
function Get-ScriptSha256 {
    if ($script:ScriptShaOverride) { return $script:ScriptShaOverride }
    if (-not $script:ScriptShaCache) { $script:ScriptShaCache = Get-NormalisedSha256 $script:SelfPath }
    return $script:ScriptShaCache
}

# The canonical spelling of a stage; anything else is refused.
function Get-CanonicalStage([string]$Stage) {
    switch ("$Stage".ToLowerInvariant()) {
        'accounts' { return 'Accounts' }
        'aclentries' { return 'AclEntries' }
        'all' { return 'All' }
        default { throw "unknown stage '$Stage'" }
    }
}

# Which parts a stage covers.
function Test-StageHas([string]$Stage, [string]$Part) {
    $st = "$Stage".ToLowerInvariant()
    if (@('accounts', 'aclentries', 'all') -cnotcontains $st) { throw "unknown stage '$Stage'" }
    switch ($Part) {
        'Accounts' { return ($st -ceq 'accounts') -or ($st -ceq 'all') }
        'Acl' { return ($st -ceq 'aclentries') -or ($st -ceq 'all') }
        default { throw "unknown stage part '$Part'" }
    }
}

# ---- access-list parsing at string level (memoised where it is called per object)
$script:AceRx = [regex]::new('\(([^;()]*);([^;()]*);([^;()]*);([^;()]*);([^;()]*);([^;()]*)\)')
$script:ExplicitMemo = @{}
$script:Intern = [System.Collections.Generic.Dictionary[string, string]]::new()

# One shared instance per distinct list text: the snapshot of ~600k objects holds a few hundred strings.
function Get-Interned([string]$Text) {
    $r = $null
    if ($script:Intern.TryGetValue($Text, [ref]$r)) { return $r }
    $script:Intern[$Text] = $Text
    return $Text
}

# Flags are a run of two-letter tokens (OI CI IO NP ID); true when the token is present.
function Test-AceFlag([string]$Flags, [string]$Token) { return [regex]::IsMatch($Flags, "^(?:..)*?$Token") }

function Get-AceInfo([string]$Sddl) {
    foreach ($m in $script:AceRx.Matches($Sddl)) {
        $g = $m.Groups
        [pscustomobject]@{ Text = $m.Value; Type = $g[1].Value; Flags = $g[2].Value; Mask = $g[3].Value; Sid = $g[6].Value; Inherited = (Test-AceFlag $g[2].Value 'ID') }
    }
}

# Purge SIDs that have an EXPLICIT (not inherited) entry in this list.
function Get-ExplicitPurgeSids([string]$Sddl, [string[]]$PurgeSids) {
    if ($script:ExplicitMemo.ContainsKey($Sddl)) { return $script:ExplicitMemo[$Sddl] }
    $r = @()
    foreach ($sid in $PurgeSids) {
        if ($Sddl.Contains($sid)) { if (@(Get-AceInfo $Sddl | Where-Object { $_.Sid -ceq $sid -and -not $_.Inherited }).Count) { $r += $sid } }
    }
    if ($script:ExplicitMemo.Count -gt 200000) { $script:ExplicitMemo.Clear() }
    $script:ExplicitMemo[$Sddl] = $r
    return $r
}

# The list with every entry naming one of the SIDs cut out, and nothing else changed (order, flags, protection kept).
function Remove-SidsFromSddl([string]$Sddl, [string[]]$Sids) {
    if (-not $Sids.Count) { return $Sddl }
    $rx = [regex]::new('\([^()]*;;;(?:' + (($Sids | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\)')
    return $rx.Replace($Sddl, '')
}
function Test-SddlHasAces([string]$Sddl) { return $script:AceRx.IsMatch($Sddl) }

# The kernel keeps the auto-inherited flag only when the request flag comes with it.
function ConvertTo-WritableSddl([string]$Sddl) {
    $i = $Sddl.IndexOf('(')
    if ($i -lt 0) { return $Sddl }
    $head = $Sddl.Substring(0, $i)
    if ($head.Contains('AI') -and -not $head.Contains('AR')) { $head = $head.Replace('AI', 'ARAI') }
    return $head + $Sddl.Substring($i)
}

# Folders whose subtrees may hold the other names of a hard-linked file: the allowlisted folders and, by the LA's decision, the pinned LinkRoots.
function Get-LinkNameRoots($Spec) {
    $r = @($Spec.AclTargets | ForEach-Object { $_.Path })
    if (Test-Gate 'link-roots') { $r += @($Spec.LinkRoots | Where-Object { $_ }) }
    return @($r)
}

# SIDs that apply at a path: those of every allowlisted folder that is the path or above it.
function Get-ScopeSids($Spec, [string]$Path) {
    $out = @()
    foreach ($t in $Spec.AclTargets) {
        $tp = $t.Path.TrimEnd('\')
        if ($Path -ieq $tp -or $Path.StartsWith($tp + '\', [StringComparison]::OrdinalIgnoreCase)) { $out += $t.Sid }
    }
    return @($out | Select-Object -Unique)
}

# ---------------------------------------------------------------- readers

function Get-AclAccess([string]$Path) {
    $fsi = if (Test-Path -LiteralPath $Path -PathType Container) { [IO.DirectoryInfo]$Path } else { [IO.FileInfo]$Path }
    return [IO.FileSystemAclExtensions]::GetAccessControl($fsi, [Security.AccessControl.AccessControlSections]::Access)
}
function Format-Ace($r) {
    '{0}:{1}:{2}:0x{3:x}:{4}' -f $r.AccessControlType, $r.InheritanceFlags, $r.PropagationFlags, [int]$r.FileSystemRights, $(if ($r.IsInherited) { 'inherited' } else { 'explicit' })
}
function Get-SidAces([string]$Path, [string]$Sid) {
    $acl = Get-AclAccess $Path
    $rules = $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -ceq $Sid }
    return @($rules | ForEach-Object { Format-Ace $_ } | Sort-Object)
}
function Get-AclTargetState($T) {
    $o = [ordered]@{ id = $T.Id; path = $T.Path; sid = $T.Sid; exists = $false; reparse = $false; aces = @(); protected = $null; owner = $null }
    if (Test-Path -LiteralPath $T.Path -PathType Container) {
        $o.exists = $true
        $o.reparse = [bool]((Get-Item -LiteralPath $T.Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)
        $acl = Get-AclAccess $T.Path
        $o.aces = Get-SidAces $T.Path $T.Sid
        $o.protected = $acl.AreAccessRulesProtected
        $o.owner = try { [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]$T.Path, [Security.AccessControl.AccessControlSections]::Owner).GetOwner([Security.Principal.SecurityIdentifier]).Value } catch { 'unreadable' }
    }
    return $o
}

function Get-UserState($Spec, $U, $CimProfiles) {
    $o = [ordered]@{ name = $U.Name; expectedSid = $U.Sid; exists = $false; sid = $null; enabled = $null; lastLogon = $null; profileListEntry = $false; profileFolders = @(); cimProfile = $false; groups = @() }
    $l = Get-LocalUserOrNull $U.Name
    if ($l) {
        $o.exists = $true; $o.sid = $l.SID.Value; $o.enabled = $l.Enabled
        $o.lastLogon = if ($l.LastLogon) { $l.LastLogon.ToString('o') } else { $null }
        $o.groups = @(Get-UserGroupNames $U.Name)
    }
    foreach ($s in @($U.Sid, $o.sid) | Where-Object { $_ } | Select-Object -Unique) {
        if (Test-Path -LiteralPath "$($Spec.ProfileListRoot)\$s") { $o.profileListEntry = $true }
        if ($CimProfiles | Where-Object { $_.SID -ceq $s }) { $o.cimProfile = $true }
    }
    if (Test-Path -LiteralPath $Spec.ProfileFolderRoot) {
        $o.profileFolders = @(Get-ChildItem -LiteralPath $Spec.ProfileFolderRoot -Directory -Force -ErrorAction Stop |
                Where-Object { $_.Name.StartsWith($U.Name, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { $_.FullName })
    }
    return $o
}
function Get-GroupState($Spec) {
    $g = $Spec.Group
    $o = [ordered]@{ name = $g.Name; expectedSid = $g.Sid; exists = $false; sid = $null; description = $null; memberSids = @() }
    $l = Get-LocalGroupOrNull $g.Name
    if ($l) {
        $o.exists = $true; $o.sid = $l.SID.Value; $o.description = $l.Description
        $o.memberSids = @(Get-GroupMemberSids $g.Name)
    }
    return $o
}
function Get-FirewallRuleState($F) {
    $o = [ordered]@{ displayName = $F.DisplayName; expectedName = $F.Name; count = 0; name = $null; enabled = $null; direction = $null; action = $null; localUser = $null }
    $r = @(Get-FirewallRulesByDisplayName $F.DisplayName)
    $o.count = $r.Count
    if ($r.Count -ge 1) {
        $o.name = ($r | ForEach-Object { $_.Name }) -join ','
        $o.enabled = [string]$r[0].Enabled; $o.direction = [string]$r[0].Direction; $o.action = [string]$r[0].Action
        $o.localUser = [string](($r[0] | Get-NetFirewallSecurityFilter).LocalUser)
    }
    return $o
}
function Get-RegistryState($Spec) {
    $p = $Spec.Registry.Path
    $o = [ordered]@{ path = $p; keyExists = $false; values = [ordered]@{}; targets = [ordered]@{} }
    if (Test-Path -LiteralPath $p) {
        $o.keyExists = $true
        $key = Get-Item -LiteralPath $p
        foreach ($n in ($key.GetValueNames() | Sort-Object)) {
            $o.values[$n] = '{0}:{1}' -f $key.GetValueKind($n), $key.GetValue($n)
        }
    }
    foreach ($n in $Spec.Registry.Names) { $o.targets[$n] = if ($o.values.Contains($n)) { $o.values[$n] } else { $null } }
    return $o
}

# The two exports must produce a recognisable file; anything else is a check that did not run.
function Get-WfpExportText([string]$Dir) {
    if ($script:SelfTestActive -and $script:ExportFault -ceq 'wfp-missing') { return $null }
    if ($script:SelfTestActive -and $script:ExportFault -ceq 'wfp-garbage') { return 'not a filter dump' }
    Push-Location $Dir
    try { & netsh wfp show filters file=wfp.xml 2>&1 | Out-Null } finally { Pop-Location }
    $p = Join-Path $Dir 'wfp.xml'
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    return [IO.File]::ReadAllText($p)
}
function Get-RightsExportText([string]$Dir) {
    if ($script:SelfTestActive -and $script:ExportFault -ceq 'rights-missing') { return $null }
    if ($script:SelfTestActive -and $script:ExportFault -ceq 'rights-garbage') { return 'not a rights dump' }
    $inf = Join-Path $Dir 'rights.inf'
    & secedit /export /cfg $inf /areas USER_RIGHTS /quiet 2>&1 | Out-Null
    if (-not (Test-Path -LiteralPath $inf)) { return $null }
    return [IO.File]::ReadAllText($inf)
}

# What counts as a usable export: anything else is a check that did not run.
function Test-WfpExportUsable($Text) { return ($null -ne $Text) -and ("$Text".IndexOf('<filters', [StringComparison]::Ordinal) -ge 0) }
function Test-RightsExportUsable($Text) { return ($null -ne $Text) -and ("$Text".IndexOf('[Privilege Rights]', [StringComparison]::Ordinal) -ge 0) }

# Rules that match the glob but are not the pinned ones.
function Get-ExtraRuleNames($Spec, $Rules) {
    return @(@($Rules) | Where-Object { $null -ne $_ } | Where-Object { $n = $_.Name; -not ($Spec.Firewall | Where-Object { $_.Name -ceq $n }) } | ForEach-Object { "$($_.DisplayName) [$($_.Name)]" })
}

# What a verify reports: pinned steps still present, findings, and (for the access-entry stage) scan problems.
function Get-VerifyProblems($Plan, $Findings, $Scans, [string]$Stage) {
    $p = [System.Collections.Generic.List[string]]::new()
    if ((Test-Gate 'empty-plan') -and @($Plan | Where-Object { $null -ne $_ }).Count -eq 0) { $p.Add("the plan for stage '$Stage' has no steps, so nothing was checked") }
    foreach ($s in @($Plan | Where-Object { $null -ne $_ })) { if ($s.present) { $p.Add("[$($s.id)] $($s.kind) still present: $($s.target)") } }
    foreach ($f in $Findings) { $p.Add($f) }
    foreach ($x in (Get-CertificationProblems $Scans)) { $p.Add($x) }
    return @($p)
}

# The verdict of an apply: nothing left, nothing uncertified, and no earlier stop.
function Get-ApplyVerdict([int]$Code, $Left, $Cert) {
    return ($Code -eq 0) -and (@($Left).Count -eq 0) -and (@($Cert).Count -eq 0)
}

function Get-HeavyState($Spec, [bool]$IsAdmin) {
    $o = [ordered]@{ checked = $false; notRun = @(); services = @(); tasks = @(); wfpHits = @(); rightsHits = @() }
    $g = $Spec.ServiceGlob
    $names = @($Spec.Users | ForEach-Object { $_.Name })
    try { $o.services = @(Get-Service -ErrorAction Stop | Where-Object { $_.Name -like "*$g*" -or $_.DisplayName -like "*$g*" } | ForEach-Object { $_.Name }) }
    catch { $o.notRun += "services (could not be listed: $($_.Exception.Message))" }
    try { $o.services += @(Get-CimInstance -ClassName Win32_Service -ErrorAction Stop | Where-Object { $sn = "$($_.StartName)"; @($names | Where-Object { $sn -ieq $_ -or $sn.EndsWith("\$_", [StringComparison]::OrdinalIgnoreCase) }).Count } | ForEach-Object { "$($_.Name) (runs as $($_.StartName))" }) }
    catch { $o.notRun += "services' accounts (could not be listed: $($_.Exception.Message))" }
    $sids = @($Spec.Users | ForEach-Object { $_.Sid })
    try { $o.tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object {
            $t = $_
            $uid = "$($t.Principal.UserId)"; $gid = "$($t.Principal.GroupId)"
            $t.TaskName -like "*$g*" -or $t.TaskPath -like "*$g*" -or ($names | Where-Object { $uid.EndsWith($_, [StringComparison]::OrdinalIgnoreCase) }) -or ($sids -ccontains $uid) -or ($gid -and ($gid -ieq $Spec.Group.Name -or $gid.EndsWith("\$($Spec.Group.Name)", [StringComparison]::OrdinalIgnoreCase) -or $gid -ceq $Spec.Group.Sid))
        } | ForEach-Object { "$($_.TaskPath)$($_.TaskName)" }) }
    catch { $o.notRun += "scheduled tasks (could not be listed: $($_.Exception.Message))" }
    if (-not $IsAdmin) { $o.notRun += 'Windows Filtering Platform filters and user-rights assignments (needs administrator)'; return $o }
    $tmp = $null
    try { $tmp = New-AdminTempDirectory } catch {
        $o.notRun += "Windows Filtering Platform filters and user-rights assignments (no protected scratch folder: $($_.Exception.Message))"
        return $o
    }
    try {
        $txt = Get-WfpExportText $tmp
        if (-not (Test-WfpExportUsable $txt)) {
            $o.notRun += 'Windows Filtering Platform filters (the netsh export produced no usable file)'
        } else {
            foreach ($n in $Spec.WfpNeedles) { if ($txt.IndexOf($n, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $o.wfpHits += $n } }
            foreach ($s in (@($Spec.Users.Sid) + $Spec.Group.Sid)) { if ($txt.IndexOf($s, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $o.wfpHits += $s } }
        }
        $txt = Get-RightsExportText $tmp
        if (-not (Test-RightsExportUsable $txt)) {
            $o.notRun += 'user-rights assignments (the secedit export produced no usable file)'
        } else {
            $o.rightsHits = @(Find-RightsHits $Spec $txt)
        }
    } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $o.checked = ($o.notRun.Count -eq 0)
    return $o
}

function Get-LiveState($Spec, [bool]$IsAdmin, [bool]$Heavy = $true, [string]$Stage = 'All') {
    $cim = @(Get-CimInstance -ClassName Win32_UserProfile -ErrorAction Stop)
    $glob = $Spec.FirewallGlob
    $extra = Get-ExtraRuleNames $Spec (Get-FirewallRulesByDisplayName "$glob*")
    return [ordered]@{
        users         = @($Spec.Users | ForEach-Object { Get-UserState $Spec $_ $cim })
        group         = Get-GroupState $Spec
        firewall      = @($Spec.Firewall | ForEach-Object { Get-FirewallRuleState $_ })
        firewallExtra = $extra
        registry      = Get-RegistryState $Spec
        acl           = $(if (Test-StageHas $Stage 'Acl') { @($Spec.AclTargets | ForEach-Object { Get-AclTargetState $_ }) } else { @() })
        heavy         = $(if ($Heavy) { Get-HeavyState $Spec $IsAdmin } else { [ordered]@{ checked = $false; notRun = @('skipped'); services = @(); tasks = @(); wfpHits = @(); rightsHits = @() } })
    }
}

# ---------------------------------------------------------------- findings and plan

# Pure over the state: each finding is a reason to change nothing.
function Get-Findings($Spec, $State) {
    $f = [System.Collections.Generic.List[string]]::new()
    if (-not (Test-Gate 'unexpected-live')) { return @() }
    foreach ($u in $State.users) {
        if ($u.exists -and $u.sid -cne $u.expectedSid) { $f.Add("account $($u.name) has SID $($u.sid), recorded $($u.expectedSid)") }
        if ($u.exists -and $u.lastLogon) { $f.Add("account $($u.name) has a logon record ($($u.lastLogon)); recorded as never logged on") }
        if ($u.profileListEntry) { $f.Add("account $($u.name) has a ProfileList entry; none recorded") }
        foreach ($gn in @($u.groups)) { if (@('Users', $Spec.Group.Name) -inotcontains $gn) { $f.Add("account $($u.name) is a member of the group '$gn'; only Users and $($Spec.Group.Name) are recorded") } }
        if ($u.cimProfile) { $f.Add("account $($u.name) has a Windows profile record; none recorded") }
        foreach ($p in $u.profileFolders) { $f.Add("a profile folder exists for $($u.name): $p; none recorded") }
    }
    $g = $State.group
    if ($g.exists) {
        if ($g.sid -cne $g.expectedSid) { $f.Add("group $($g.name) has SID $($g.sid), recorded $($g.expectedSid)") }
        if ($g.description -cne $Spec.Group.Description) { $f.Add("group $($g.name) description is '$($g.description)', recorded '$($Spec.Group.Description)'") }
        $allowed = @($Spec.Users | ForEach-Object { $_.Sid })
        foreach ($m in $g.memberSids) { if ($allowed -cnotcontains $m) { $f.Add("group $($g.name) has a member not on the allowlist: $m") } }
    }
    foreach ($r in $State.firewall) {
        if ($r.count -gt 1) { $f.Add("$($r.count) firewall rules are named $($r.displayName); expected at most 1") }
        if ($r.count -eq 1) {
            if ($r.name -cne $r.expectedName) { $f.Add("firewall rule $($r.displayName) has id $($r.name), recorded $($r.expectedName)") }
            if ($r.direction -ne 'Outbound' -or $r.action -ne 'Block') { $f.Add("firewall rule $($r.displayName) is $($r.direction)/$($r.action), recorded Outbound/Block") }
            $want = ($Spec.Firewall | Where-Object { $_.DisplayName -ceq $r.displayName }).UserSid
            if (-not (Test-ScopeOnlySid ([string]$r.localUser) $want)) { $f.Add("firewall rule $($r.displayName) is not scoped to the one account SID $want") }
        }
    }
    foreach ($e in $State.firewallExtra) { $f.Add("another rule matches '$($Spec.FirewallGlob)' and is not on the allowlist: $e") }
    foreach ($n in $Spec.Registry.Names) {
        $v = $State.registry.targets[$n]
        if ($null -ne $v -and $v -cne 'DWord:0') { $f.Add("registry value $n is '$v', recorded DWord:0") }
    }
    $h = $State.heavy
    if (-not $h.checked) { foreach ($n in $h.notRun) { $f.Add("a safety check could not run, so it cannot be ruled out: $n") } }
    foreach ($s in $h.services) { $f.Add("a service matches '$($Spec.ServiceGlob)': $s") }
    foreach ($t in $h.tasks) { $f.Add("a scheduled task matches: $t") }
    foreach ($w in $h.wfpHits) { $f.Add("a Windows Filtering Platform filter mentions '$w'") }
    foreach ($r in $h.rightsHits) { $f.Add("a user-rights assignment names '$r'") }
    foreach ($a in $State.acl) {
        if ($a.exists -and $a.reparse) { $f.Add("$($a.path) is a link (reparse point)") }
    }
    return @($f)
}

function Get-Plan($Spec, $State, [string]$Stage = 'All') {
    $steps = [System.Collections.Generic.List[object]]::new()
    foreach ($t in $(if (Test-StageHas $Stage 'Acl') { $Spec.AclTargets } else { @() })) {
        $a = $State.acl | Where-Object { $_.id -ceq $t.Id }
        $st = "aces=[$($a.aces -join ' ')];protected=$($a.protected);owner=$($a.owner)"
        $steps.Add([ordered]@{ id = $t.Id; kind = 'acl'; target = $t.Path; present = ($a.aces.Count -gt 0); state = $st
                what = "access entries for SID $($t.Sid)"; reversible = $true })
    }
    if (-not (Test-StageHas $Stage 'Accounts')) { return @($steps) }
    $d = 1
    foreach ($u in $State.users) {
        $steps.Add([ordered]@{ id = "D$d"; kind = 'disable'; target = $u.name; present = ($u.exists -and $u.enabled -ne $false)
                state = "sid=$($u.sid);enabled=$($u.enabled)"
                what = 'disable the account first (reversible; it stays until the deletion step)'; reversible = $true }); $d++
    }
    $i = 5
    foreach ($f in $Spec.Firewall) {
        $r = $State.firewall | Where-Object { $_.displayName -ceq $f.DisplayName }
        $steps.Add([ordered]@{ id = "A$i"; kind = 'firewall'; target = $f.DisplayName; present = ($r.count -gt 0)
                state = "count=$($r.count);name=$($r.name);enabled=$($r.enabled);dir=$($r.direction);action=$($r.action);user=$($r.localUser)"
                what = 'firewall rule'; reversible = $true }); $i++
    }
    foreach ($n in $Spec.Registry.Names) {
        $v = $State.registry.targets[$n]
        $steps.Add([ordered]@{ id = 'A4'; kind = 'registry'; target = "$($Spec.Registry.Path) :: $n"; present = ($null -ne $v); state = "value=$v"
                what = 'hidden-user value'; reversible = $true })
    }
    $k = 1
    foreach ($u in $State.users) {
        $steps.Add([ordered]@{ id = "A$k"; kind = 'user'; target = $u.name; present = $u.exists
                state = "sid=$($u.sid);enabled=$($u.enabled);lastLogon=$($u.lastLogon)"
                what = 'local account'; reversible = $false }); $k++
    }
    $g = $State.group
    $steps.Add([ordered]@{ id = 'A3'; kind = 'group'; target = $g.name; present = $g.exists; state = "sid=$($g.sid);members=$($g.memberSids -join ',')"
            what = 'local group'; reversible = $false })
    return @($steps)
}

function Get-PlanDigest($Spec, $Plan, [string]$Stage = 'All') {
    $lines = @("spec=$(Get-SpecDigest $Spec)", "stage=$(Get-CanonicalStage $Stage)", "script=$(Get-ScriptSha256)") + @($Plan | ForEach-Object { "$($_.id)|$($_.kind)|$($_.target)|$($_.present)|$($_.state)" })
    $h = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes(($lines -join "`n")))
    return ([BitConverter]::ToString($h) -replace '-', '').ToLowerInvariant()
}

# ---------------------------------------------------------------- guarded destructive helpers

# Identity checks, kept as small functions so each can be driven (and broken) on its own.
function Assert-UserIdentity($Entry, [string]$LiveSid, [string]$Name) {
    if ($Entry.Sid -and $LiveSid -cne $Entry.Sid) {
        if (Test-Gate 'sid-match') { Refuse 'sid-match' "account '$Name' has SID $LiveSid, recorded $($Entry.Sid)" }
    }
}
function Assert-NoProfile($State, [string]$Name) {
    if (($State.profileListEntry -or $State.cimProfile -or @($State.profileFolders).Count) -and (Test-Gate 'no-profile')) {
        Refuse 'no-profile' "account '$Name' has a profile; none recorded"
    }
}
function Assert-GroupIdentity($Group, [string]$LiveSid, [string]$Name) {
    if ($Group.Sid -and $LiveSid -cne $Group.Sid) {
        if (Test-Gate 'sid-match') { Refuse 'sid-match' "group '$Name' has SID $LiveSid, recorded $($Group.Sid)" }
    }
}
function Assert-GroupMembers([string[]]$Members, [string[]]$AllowedSids, [string]$Name) {
    $foreign = @($Members | Where-Object { $AllowedSids -cnotcontains $_ })
    if ($foreign.Count -and (Test-Gate 'group-members')) { Refuse 'group-members' "group '$Name' has members not on the allowlist: $($foreign -join ', ')" }
}
function Assert-FirewallIdentity($Entry, $Live, [string]$LocalUser, [string]$DisplayName) {
    if (Test-Gate 'fw-identity') {
        $l = @($Live)
        if ($l.Count -ne 1) { Refuse 'fw-identity' "$($l.Count) rules are named '$DisplayName'" }
        if ($Entry.Name -and $l[0].Name -cne $Entry.Name) { Refuse 'fw-identity' "rule '$DisplayName' has id $($l[0].Name), recorded $($Entry.Name)" }
        if ($Entry.UserSid -and -not (Test-ScopeOnlySid $LocalUser $Entry.UserSid)) { Refuse 'fw-identity' "rule '$DisplayName' is not scoped to exactly $($Entry.UserSid)" }
    }
}
function Assert-RegistryShape([string]$Kind, $Value, [string]$Name) {
    if ((Test-Gate 'reg-value-shape') -and ('{0}:{1}' -f $Kind, $Value) -cne 'DWord:0') {
        Refuse 'reg-value-shape' "registry value '$Name' is not the recorded DWORD 0"
    }
}

function Disable-AllowedUser($Spec, [string]$Name) {
    Assert-SpecAllowed $Spec
    Assert-NoWildcard $Name 'account name'
    $e = @($Spec.Users | Where-Object { $_.Name -ceq $Name })
    if ($e.Count -ne 1) {
        if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' "account '$Name' is not on the allowlist" }
        $e = @([ordered]@{ Name = $Name; Sid = $null })
    }
    $live = Get-LocalUser -Name $Name -ErrorAction Stop
    Assert-UserIdentity $e[0] $live.SID.Value $Name
    $sid = $live.SID
    Invoke-Destructive 'user-disable' $Name { Disable-LocalUser -SID $sid -ErrorAction Stop }
}

function Remove-AllowedUser($Spec, [string]$Name) {
    Assert-SpecAllowed $Spec
    Assert-NoWildcard $Name 'account name'
    $e = @($Spec.Users | Where-Object { $_.Name -ceq $Name })
    if ($e.Count -ne 1) {
        if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' "account '$Name' is not on the allowlist" }
        $e = @([ordered]@{ Name = $Name; Sid = $null })
    }
    $live = Get-LocalUser -Name $Name -ErrorAction Stop
    Assert-UserIdentity $e[0] $live.SID.Value $Name
    $cim = @(Get-CimInstance -ClassName Win32_UserProfile -ErrorAction Stop)
    $st = Get-UserState $Spec ([ordered]@{ Name = $Name; Sid = $live.SID.Value }) $cim
    Assert-NoProfile $st $Name
    $sid = $live.SID
    Invoke-Destructive 'user' $Name { Remove-LocalUser -SID $sid -ErrorAction Stop }
}

function Remove-AllowedGroup($Spec, [string]$Name) {
    Assert-SpecAllowed $Spec
    Assert-NoWildcard $Name 'group name'
    $g = $Spec.Group
    if ($g.Name -cne $Name) {
        if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' "group '$Name' is not on the allowlist" }
        $g = [ordered]@{ Name = $Name; Sid = $null }
    }
    $live = Get-LocalGroup -Name $Name -ErrorAction Stop
    Assert-GroupIdentity $g $live.SID.Value $Name
    Assert-GroupMembers @(Get-GroupMemberSids $Name) @($Spec.Users | ForEach-Object { $_.Sid }) $Name
    $sid = $live.SID
    Invoke-Destructive 'group' $Name { Remove-LocalGroup -SID $sid -ErrorAction Stop }
}

function Remove-AllowedFirewallRule($Spec, [string]$DisplayName) {
    Assert-SpecAllowed $Spec
    $e = @($Spec.Firewall | Where-Object { $_.DisplayName -ceq $DisplayName })
    if ($e.Count -ne 1) {
        if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' "firewall rule '$DisplayName' is not on the allowlist" }
        $e = @([ordered]@{ DisplayName = $DisplayName; Name = $null; UserSid = $null })
    }
    Assert-NoWildcard $DisplayName 'rule name'
    $live = @(Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction Stop)
    $lu = if ($live.Count -eq 1) { [string](($live[0] | Get-NetFirewallSecurityFilter).LocalUser) } else { '' }
    Assert-FirewallIdentity $e[0] $live $lu $DisplayName
    $id = $live[0].Name
    Invoke-Destructive 'firewall' $DisplayName { Remove-NetFirewallRule -Name $id -ErrorAction Stop }
}

function Remove-AllowedRegistryValue($Spec, [string]$Name) {
    Assert-SpecAllowed $Spec
    Assert-NoWildcard $Name 'registry value'
    if ($Spec.Registry.Names -cnotcontains $Name) {
        if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' "registry value '$Name' is not on the allowlist" }
    }
    $p = $Spec.Registry.Path
    $key = Get-Item -LiteralPath $p -ErrorAction Stop
    if ($key.GetValueNames() -cnotcontains $Name) { return }
    Assert-RegistryShape ([string]$key.GetValueKind($Name)) $key.GetValue($Name) $Name
    Invoke-Destructive 'registry' "$p::$Name" { Remove-ItemProperty -LiteralPath $p -Name $Name -ErrorAction Stop }
}

# One object: opened once, checked on that handle, the Codex entries cut out of its list as it stands, written back
# through the same handle. Returns 'changed', 'unchanged' or a text beginning 'refused:' / 'failed:'.
function Remove-ObjectSids([string]$Path, [string[]]$Sids, [string[]]$Roots = @()) {
    $h = $null
    try {
        $h = [OpAcl]::Open($Path)
        if (Test-Gate 'acl-handle') {
            $i = [OpAcl]::Inspect($h)
            if ($i.FinalPath -ine ('\\?\' + $Path)) { return "refused: resolves to $($i.FinalPath), not to this path" }
            if (-not $i.IsDirectory -and $i.Links -gt 1) {
                $outside = @([OpAcl]::LinkNames($Path) | Where-Object { $nm = $_; -not @($Roots | Where-Object { $nm -ieq $_.TrimEnd('\') -or $nm.StartsWith($_.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) }).Count })
                if ($outside.Count) { return "refused: a file with $($i.Links) names, $($outside.Count) outside the allowlisted folders (hard links share one access list), e.g. $($outside[0])" }
            }
        }
        $old = [OpAcl]::GetSddl($h)
        $new = Remove-SidsFromSddl $old $Sids
        if ($new -ceq $old) { return 'unchanged' }
        if ((Test-Gate 'empty-after') -and -not (Test-SddlHasAces $new)) { return 'refused: it would leave an empty access list (no one could open it)' }
        $write = ConvertTo-WritableSddl $new
        $handle = $h
        Invoke-Destructive 'acl-object' $Path { if (-not ($script:SelfTestActive -and $script:WriteFault)) { [OpAcl]::SetSddl($handle, $write) } }
        if (-not $script:SimulateOnly) {
            $back = [OpAcl]::GetSddl($h)
            if ($back -cne $new) { return "failed: read back $back, wanted $new" }
        }
        return 'changed'
    } catch { return "failed: $($_.Exception.Message)" }
    finally { if ($h) { $h.Dispose() } }
}

# Walks one allowlisted folder top-down and cuts the Codex entries out of every object's own list. Nothing is
# re-derived or propagated, so every other entry stays exactly as it was.
function Remove-SidAcesTree($Spec, [string]$RootPath, [int]$Seconds = 1800) {
    Assert-SpecAllowed $Spec
    $t = @($Spec.AclTargets | Where-Object { $_.Path -ceq $RootPath })
    $fallback = @()
    if ($t.Count -ne 1) {
        if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' "path '$RootPath' is not on the allowlist" }
        $fallback = @($Spec.AclTargets[0].Sid)
    }
    if (-not (Test-Path -LiteralPath $RootPath -PathType Container)) { Refuse 'acl-path' "'$RootPath' is not an existing folder" }
    if ((Test-Gate 'acl-reparse') -and ((Get-Item -LiteralPath $RootPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Refuse 'acl-reparse' "'$RootPath' is a link; access entries are never changed through links"
    }
    Initialize-OpNative
    [void][OpAcl]::EnablePrivilege('SeRestorePrivilege'); [void][OpAcl]::EnablePrivilege('SeBackupPrivilege')
    $roots = Get-LinkNameRoots $Spec
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $stack = [System.Collections.Generic.Stack[string]]::new(); $stack.Push($RootPath)
    $problems = [System.Collections.Generic.List[string]]::new()
    $n = [ordered]@{ visited = 0; changed = 0; unchanged = 0; left = 0 }
    $nextNote = 60
    $doOne = {
        param($p)
        $n.visited++
        if ($script:SelfTestActive -and $script:WalkHook) { & $script:WalkHook $p }
        $scope = if ($fallback.Count) { $fallback } else { Get-ScopeSids $Spec $p }
        $r = Remove-ObjectSids $p $scope $roots
        if ($r -ceq 'changed') { $n.changed++ } elseif ($r -ceq 'unchanged') { $n.unchanged++ } else { $problems.Add("$p : $r") }
    }
    while ($stack.Count) {
        if ($sw.Elapsed.TotalSeconds -gt $Seconds) { $n.left = $stack.Count; break }
        if ($script:ProgressOn -and $sw.Elapsed.TotalSeconds -gt $nextNote) { Write-Host ("    ... {0}: {1} objects visited, {2} changed in {3:n0}s" -f $RootPath, $n.visited, $n.changed, $sw.Elapsed.TotalSeconds); $nextNote += 60 }
        $d = $stack.Pop()
        & $doOne $d
        try { $children = @([IO.DirectoryInfo]::new('\\?\' + $d).EnumerateFileSystemInfos()) }
        catch { if (-not (Test-ObjectVanished $_.Exception)) { $problems.Add("$d : failed: cannot list it ($($_.Exception.Message))") }; continue }
        foreach ($ch in $children) {
            $cp = $ch.FullName -replace '^\\\\\?\\', ''
            if ($ch -is [IO.DirectoryInfo] -and -not ($ch.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $stack.Push($cp) }
            else { & $doOne $cp }
        }
    }
    $script:LastRemoval = [ordered]@{ root = $RootPath; visited = $n.visited; changed = $n.changed; unchanged = $n.unchanged; problems = @($problems); foldersLeft = $n.left; seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
    if ($problems.Count -or $n.left) {
        throw "$($problems.Count) object(s) under $RootPath were not changed safely and $($n.left) folder(s) were left at the time limit; first: $(($problems | Select-Object -First 3) -join ' || ')"
    }
    return $script:LastRemoval
}

# Puts recorded access lists back through a handle, exactly (inherited flags included).
function Invoke-RestoreAcl($Spec, [string]$Dir, [string]$OnlyPath = '', [bool]$IsAdmin = (Test-Elevated)) {
    Assert-Elevated $IsAdmin
    if (($Spec.Mode -ceq 'real') -and (Test-Gate 'restore-real-blocked')) { Refuse 'restore-real-blocked' 'restoring access lists on the real machine is not enabled until the access-entry stage has been reviewed' }
    Assert-SpecAllowed $Spec
    Assert-AdminOnlyDirectory $Dir
    $snap = Join-Path $Dir 'tree-snapshot.tsv'
    $metaPath = "$snap.meta.json"
    if (-not (Test-Path -LiteralPath $snap) -or -not (Test-Path -LiteralPath $metaPath)) { Refuse 'restore-baseline' "no completed snapshot in '$Dir'" }
    $meta = Get-Content -Raw -LiteralPath $metaPath | ConvertFrom-Json
    if ((Test-Gate 'restore-baseline') -and ((Get-FileHash -Algorithm SHA256 -LiteralPath $snap).Hash -cne $meta.sha256)) { Refuse 'restore-baseline' 'the snapshot does not match the hash recorded when it was written' }
    Initialize-OpNative
    [void][OpAcl]::EnablePrivilege('SeRestorePrivilege'); [void][OpAcl]::EnablePrivilege('SeBackupPrivilege')
    $done = 0; $same = 0; $problems = [System.Collections.Generic.List[string]]::new()
    foreach ($l in [IO.File]::ReadLines($snap)) {
        $i = $l.IndexOf("`t")
        if ($i -lt 1 -or $l.StartsWith('!unreadable')) { continue }
        $p = $l.Substring(0, $i); $want = $l.Substring($i + 1)
        if ($OnlyPath -and $p -ine $OnlyPath) { continue }
        if ((Test-Gate 'restore-path') -and -not @(Get-ScopeSids $Spec $p).Count) { Refuse 'restore-path' "'$p' is not under an allowlisted folder" }
        $h = $null
        try {
            $h = [OpAcl]::Open($p)
            $info = [OpAcl]::Inspect($h)
            if ((Test-Gate 'acl-handle') -and ($info.FinalPath -ine ('\\?\' + $p))) { $problems.Add("$p : resolves to $($info.FinalPath)"); continue }
            if ((Test-Gate 'acl-handle') -and (-not $info.IsDirectory) -and ($info.Links -gt 1)) { $problems.Add("$p : a file with $($info.Links) names"); continue }
            if ([OpAcl]::GetSddl($h) -ceq $want) { $same++; continue }
            $handle = $h; $text = ConvertTo-WritableSddl $want
            Invoke-Destructive 'acl-restore' $p { [OpAcl]::SetSddl($handle, $text) }
            if (-not $script:SimulateOnly -and ([OpAcl]::GetSddl($h) -cne $want)) { $problems.Add("$p : read back differs"); continue }
            $done++
        } catch { $problems.Add("$p : $($_.Exception.Message)") }
        finally { if ($h) { $h.Dispose() } }
    }
    return [ordered]@{ restored = $done; alreadyAsRecorded = $same; problems = @($problems) }
}

# Earlier apply folders for this spec that changed access lists and never finished cleanly.
function Get-IncompleteRuns($Spec, [string]$BackupRoot) {
    $out = @()
    if (-not $BackupRoot -or -not (Test-Path -LiteralPath $BackupRoot)) { return $out }
    $digest = Get-SpecDigest $Spec
    foreach ($d in @(Get-ChildItem -LiteralPath $BackupRoot -Directory -Filter 'remove-codex-*' -Force)) {
        $bj = Join-Path $d.FullName 'backup.json'
        if (-not (Test-Path -LiteralPath $bj)) { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $d.FullName 'tree-snapshot.tsv.meta.json'))) { continue }   # killed before its snapshot was complete: nothing had been changed
        if (Test-Path -LiteralPath (Join-Path $d.FullName 'resolved.txt')) { continue }
        try { $b = Get-Content -Raw -LiteralPath $bj | ConvertFrom-Json } catch { $out += $d.FullName; continue }
        if ($b.specDigest -cne $digest) { continue }
        $done = $false
        $rp = Join-Path $d.FullName 'report.json'
        if (Test-Path -LiteralPath $rp) { try { $done = ((Get-Content -Raw -LiteralPath $rp | ConvertFrom-Json).verdict -ceq 'PASS') } catch { $done = $false } }
        if (-not $done) { $out += $d.FullName }
    }
    return @($out)
}

# The before-change lists the read-back compares with: this run's own snapshot, unless an earlier run left work
# unfinished - then THAT run's snapshot, so what it changed is still seen.
function Resolve-ResumeBaseline($Spec, [string]$BackupRoot, [string]$ResumeFrom) {
    $inc = @(Get-IncompleteRuns $Spec $BackupRoot)
    if (-not $ResumeFrom) {
        if ($inc.Count -and (Test-Gate 'resume-required')) {
            Refuse 'resume-required' ("an earlier apply started on these folders and did not finish cleanly: " + ($inc -join '; ') + ". Its before-change snapshot is the baseline that shows what it changed. Run again with -ResumeFrom <that folder>.")
        }
        return $null
    }
    $full = [IO.Path]::GetFullPath($ResumeFrom).TrimEnd('\')
    if (@($inc | ForEach-Object { $_.TrimEnd('\') }) -inotcontains $full) { Refuse 'resume-target' "'$full' is not an unfinished apply folder for this spec under '$BackupRoot'" }
    if ($inc.Count -gt 1) { Refuse 'resume-required' ("more than one earlier apply is unfinished: " + ($inc -join '; ') + ". Resolve them one at a time.") }
    Assert-AdminOnlyDirectory $full
    $snap = Join-Path $full 'tree-snapshot.tsv'
    $meta = Get-Content -Raw -LiteralPath "$snap.meta.json" | ConvertFrom-Json
    if ((Test-Gate 'resume-baseline') -and ((Get-FileHash -Algorithm SHA256 -LiteralPath $snap).Hash -cne $meta.sha256)) { Refuse 'resume-baseline' 'the earlier snapshot does not match the hash recorded when it was written' }
    return [ordered]@{ dir = $full; before = (Read-TreeSnapshot $snap) }
}

# ---------------------------------------------------------------- backup

# Other apply folders of this same plan under the backup root: a re-run after a stop lists already-removed items as gone,
# so what an earlier run removed is only in that run's folder.
function Get-EarlierRunFolders($Spec, [string]$Root) {
    $out = @()
    if (-not $Root -or -not (Test-Path -LiteralPath $Root)) { return $out }
    $digest = Get-SpecDigest $Spec
    foreach ($d in @(Get-ChildItem -LiteralPath $Root -Directory -Filter 'remove-codex-*' -Force)) {
        $bj = Join-Path $d.FullName 'backup.json'
        if (-not (Test-Path -LiteralPath $bj)) { continue }
        try { if ((Get-Content -Raw -LiteralPath $bj | ConvertFrom-Json).specDigest -ceq $digest) { $out += $d.FullName } } catch { $out += $d.FullName }
    }
    return @($out)
}

function New-UndoText($Spec, $State, [string]$SnapshotName = 'tree-snapshot.tsv', [string]$Stage = 'All', [string[]]$Earlier = @()) {
    $L = [System.Collections.Generic.List[string]]::new()
    $L.Add('# Undo notes. Run nothing here unless you want a removed item back. Elevated pwsh.')
    $L.Add('# Accounts and the group CANNOT be restored: a recreated account gets a new SID.')
    $L.Add('# Codex''s own elevated setup recreates them if ever wanted.')
    if ($Earlier.Count) { $L.Add('# This is not the first run against this plan. Items an EARLIER run already removed (rules, values) are only in the undo notes of those folders: ' + ($Earlier -join '; ')) }
    foreach ($u in @($State.users | Where-Object { $_.exists -and $_.enabled -ne $false })) { $L.Add("# This run disables the account first; to re-enable it while it still exists: Enable-LocalUser -SID '$($u.sid)'") }
    foreach ($f in $State.firewall) {
        if ($f.count -ge 1) {
            $r = Get-NetFirewallRule -DisplayName $f.displayName
            $pf = $r | Get-NetFirewallPortFilter; $af = $r | Get-NetFirewallAddressFilter; $sf = $r | Get-NetFirewallSecurityFilter
            $ports = ''
            foreach ($pn in 'RemotePort', 'LocalPort') { $pv = @($pf.$pn); if ($pv.Count -and "$($pv -join '')" -ne 'Any' -and "$($pv -join '')" -ne '') { $ports += " -$pn $((@($pv) | ForEach-Object { "'$_'" }) -join ',')" } }
            $L.Add("# The rule below is scoped to $($sf.LocalUser), an account this run deletes: restored, it is scoped to a SID that no longer resolves.")
            $L.Add("New-NetFirewallRule -Name '$($r.Name)' -DisplayName '$($r.DisplayName)' -Description '$($r.Description)' -Direction $($r.Direction) -Action $($r.Action) -Profile Any -Protocol $($pf.Protocol)$ports -RemoteAddress $((@($af.RemoteAddress) | ForEach-Object { "'$_'" }) -join ',') -LocalUser '$($sf.LocalUser)' -Enabled $($r.Enabled)")
        }
    }
    foreach ($n in $Spec.Registry.Names) {
        if ($null -ne $State.registry.targets[$n]) { $L.Add("New-ItemProperty -LiteralPath '$($Spec.Registry.Path)' -Name '$n' -PropertyType DWord -Value 0") }
    }
    if (-not (Test-StageHas $Stage 'Acl')) { $L.Add('# Stage Accounts: no access list was read, changed or recorded by this run.'); return ($L -join "`r`n") + "`r`n" }
    $L.Add('# Access lists: the exact list of every object under the BlarAI folder, Temp and C:\ovms before the change is in ' + $SnapshotName + ' (path, tab, list).')
    $L.Add('# The change cut only the Codex entries out of each list and wrote the rest back as it was, so restoring puts every list back exactly, inherited flags included.')
    $L.Add("# Restore one object or all of them (elevated pwsh; the backup folder is protected and must still be):")
    $L.Add("#   pwsh -File '$PSCommandPath' -RestoreAcl '$(Split-Path -Parent $SnapshotName)' -RestorePath 'C:\path\of\one\object'     (omit -RestorePath to restore every recorded object)")
    return ($L -join "`r`n") + "`r`n"
}

function Write-Backup($Spec, $State, [string]$PlanDigest, [string]$Root, [int]$SnapSecs = 1800, [string]$Stage = 'All') {
    $dir = Join-Path $Root ('remove-codex-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
    try {
        if (-not (Test-Path -LiteralPath $Root)) {
            $par = Split-Path -Parent $Root
            if (($par -ieq $script:AdminTempRoot) -and -not (Test-Path -LiteralPath $par)) { New-AdminOnlyDirectory $par }
            $parOk = try { Assert-AdminOnlyDirectory $par; $true } catch { $false }
            if ($parOk) { New-AdminOnlyDirectory $Root } else { New-Item -ItemType Directory -Path $Root -Force | Out-Null }
        }
        New-AdminOnlyDirectory $dir
        $sddl = [ordered]@{}
        if (Test-StageHas $Stage 'Acl') { foreach ($t in $Spec.AclTargets) { if (Test-Path -LiteralPath $t.Path -PathType Container) { $sddl[$t.Path] = (Get-AclAccess $t.Path).GetSecurityDescriptorSddlForm('Access') } } }
        $listing = @()
        if (Test-Path -LiteralPath $Spec.ReportOnly) {
            $listing = @(Get-ChildItem -LiteralPath $Spec.ReportOnly -Force | ForEach-Object { [ordered]@{ name = $_.Name; dir = $_.PSIsContainer; bytes = $(if ($_.PSIsContainer) { $null } else { $_.Length }) } })
        }
        $doc = [ordered]@{ specDigest = Get-SpecDigest $Spec; planDigest = $PlanDigest; written = (Get-Date).ToString('o'); computer = $env:COMPUTERNAME
            stage = $Stage; state = $State; rootAclSddl = $sddl; leftAloneListing = $listing }
        $jsonPath = Join-Path $dir 'backup.json'
        $json = $doc | ConvertTo-Json -Depth 10
        [IO.File]::WriteAllText($jsonPath, $json, [Text.UTF8Encoding]::new($false))
        $undoPath = Join-Path $dir 'undo-commands.txt'
        [IO.File]::WriteAllText($undoPath, (New-UndoText $Spec $State (Join-Path $dir 'tree-snapshot.tsv') $Stage (Get-EarlierRunFolders $Spec $Root)), [Text.UTF8Encoding]::new($false))
        if ($script:BackupTamper) { & $script:BackupTamper $jsonPath }
        $script:LastSnapshot = $null
        $want = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($json))
        $back = [IO.File]::ReadAllBytes($jsonPath)
        $got = [Security.Cryptography.SHA256]::HashData($back)
        $parsed = [Text.Encoding]::UTF8.GetString($back) | ConvertFrom-Json
        $ok = ([BitConverter]::ToString($want) -ceq [BitConverter]::ToString($got)) -and $parsed.planDigest -ceq $PlanDigest -and (Test-Path $undoPath) -and ((Get-Item $undoPath).Length -gt 0)
        if (-not $ok -and (Test-Gate 'backup-readback')) { Refuse 'backup-readback' 'the backup could not be read back identical' }
        if (Test-StageHas $Stage 'Acl') { $script:LastSnapshot = Write-TreeSnapshot $Spec (Join-Path $dir 'tree-snapshot.tsv') $SnapSecs }
    } catch {
        if ($_.Exception.Message -like 'REFUSED`[*') { throw }
        if (Test-Gate 'backup-readback') { Refuse 'backup-readback' "the backup could not be written: $($_.Exception.Message)" }
    }
    return $dir
}

# ---------------------------------------------------------------- deep scan

# An object deleted between listing and reading (Temp churns) is gone, not unreadable.
function Test-ObjectVanished($Ex) {
    $e = if ($Ex.InnerException) { $Ex.InnerException } else { $Ex }
    return ($e -is [IO.FileNotFoundException]) -or ($e -is [IO.DirectoryNotFoundException])
}

# Walks a tree (never through links) and reads every object's access list.
#   -Writer: also records "path<TAB>list" per object (the undo file).   -Collect: also keeps them in memory.
#   -Before + -DropSids: compares each object with its before-change list; the expected difference is exactly the
#   entries of the dropped SIDs, anything else is reported as a difference (a loss or a gain alike).
#   -Pre: pre-change checks (explicit Codex entries below the roots, lists that would be left empty).
function Find-SidAcesDeep([string]$Root, [string[]]$Sids, [int]$Seconds, $Writer = $null, $Before = $null, [string[]]$DropSids = @(), $Pre = $null, $Collect = $null) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $stack = [System.Collections.Generic.Stack[string]]::new(); $stack.Push($Root)
    $hits = [System.Collections.Generic.List[string]]::new(); $hitSids = [System.Collections.Generic.HashSet[string]]::new()
    $collateral = [System.Collections.Generic.List[string]]::new()
    $explicit = [System.Collections.Generic.List[string]]::new(); $empty = [System.Collections.Generic.List[string]]::new()
    $firstUnread = [System.Collections.Generic.List[string]]::new()
    $emptyMemo = @{}
    $c = [ordered]@{ scanned = 0; unreadable = 0; vanished = 0; left = 0; matched = 0; added = 0; fast = 0; slow = 0 }
    # The dropped SIDs' entries as one pattern: cutting them out of the old list gives the expected new list, so an
    # object that differs only by those needs no parse at all.
    $dropRx = if ($DropSids.Count) { [regex]::new('\([^()]*;;;(?:' + (($DropSids | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\)') } else { $null }
    $nextNote = 60
    # Objects are opened through the extended-length form so names Win32 normalises away (trailing dot or
    # space) are read like any other; reported names drop the prefix.
    $check = {
        param($fsi)
        $plain = $fsi.FullName -replace '^\\\\\?\\', ''
        try {
            if ($script:SelfTestActive -and $script:ReadFault -and (& $script:ReadFault $plain)) { throw [UnauthorizedAccessException]::new('injected read fault') }
            $acl = if ($fsi -is [IO.DirectoryInfo]) { [IO.FileSystemAclExtensions]::GetAccessControl($fsi, [Security.AccessControl.AccessControlSections]::Access) } else { [IO.FileSystemAclExtensions]::GetAccessControl([IO.FileInfo]$fsi, [Security.AccessControl.AccessControlSections]::Access) }
            $s = Get-Interned $acl.GetSecurityDescriptorSddlForm('Access')
            $c.scanned++
            $found = $false
            foreach ($sid in $Sids) { if ($s.Contains($sid)) { $found = $true; [void]$hitSids.Add($sid) } }
            if ($found) { $hits.Add($plain) }
            if ($Writer) { $Writer.WriteLine("$plain`t$s") }
            if ($Collect) { $Collect[$plain] = $s }
            if ($Pre) {
                foreach ($sid in (Get-ExplicitPurgeSids $s $Pre.Purge)) { if (-not $Pre.Exempt.ContainsKey("$plain|$sid")) { $explicit.Add("$plain  $sid") } }
                if ($found) {
                    if (-not $emptyMemo.ContainsKey($s)) { $emptyMemo[$s] = (Test-SddlHasAces (Remove-SidsFromSddl $s $Pre.Purge)) }
                    if (-not $emptyMemo[$s]) { $empty.Add($plain) }
                }
            }
            if ($Before) {
                $old = $null
                if (-not $Before.TryGetValue($plain, [ref]$old)) { $c.added++ }
                else {
                    $c.matched++
                    if ($old -cne $s) {
                        if ($dropRx -and ($dropRx.Replace($old, '') -ceq $s)) { $c.fast++ }
                        else { $c.slow++; $d = Get-AceDelta $old $s $DropSids; if ($d) { $collateral.Add("$plain  $d") } }
                    }
                }
            }
        } catch {
            if (Test-ObjectVanished $_.Exception) { $c.vanished++ }
            else {
                $c.unreadable++
                if ($firstUnread.Count -lt 5) { $firstUnread.Add($plain) }
                if ($Writer) { $Writer.WriteLine("!unreadable`t$plain") }
            }
        }
    }
    & $check ([IO.DirectoryInfo]::new('\\?\' + $Root))
    while ($stack.Count) {
        if ($sw.Elapsed.TotalSeconds -gt $Seconds) { $c.left = $stack.Count; break }
        if ($script:ProgressOn -and $sw.Elapsed.TotalSeconds -gt $nextNote) { Write-Host ("    ... {0}: {1} objects read in {2:n0}s" -f $Root, $c.scanned, $sw.Elapsed.TotalSeconds); $nextNote += 60 }
        $d = $stack.Pop()
        try { $children = @([IO.DirectoryInfo]::new('\\?\' + $d).EnumerateFileSystemInfos()) } catch { if (Test-ObjectVanished $_.Exception) { $c.vanished++ } else { $c.unreadable++; if ($firstUnread.Count -lt 5) { $firstUnread.Add($d) }; if ($Writer) { $Writer.WriteLine("!unreadable`t$d") } }; continue }
        foreach ($ch in $children) {
            & $check $ch
            if ($ch -is [IO.DirectoryInfo] -and -not ($ch.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $stack.Push(($ch.FullName -replace '^\\\\\?\\', '')) }
        }
    }
    $missing = 0
    if ($Before) {
        $prefix = $Root.TrimEnd('\') + '\'
        $inTree = 0
        foreach ($k in $Before.Keys) { if ($k.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or $k.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { $inTree++ } }
        $missing = [math]::Max(0, $inTree - $c.matched)
    }
    return [ordered]@{ root = $Root; scanned = $c.scanned; unreadable = $c.unreadable; vanished = $c.vanished; hits = $hits.Count; firstHits = @($hits | Select-Object -First 5); hitSids = @($hitSids); foldersLeftUnscanned = $c.left
        firstUnreadable = @($firstUnread); explicitCodex = @($explicit); emptyAfter = @($empty)
        matchedBefore = $c.matched; notInBefore = $c.added; missingNow = $missing; fastCompared = $c.fast; slowCompared = $c.slow; collateral = @($collateral); seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
}

# A scan certifies only when it finished, read every object and found nothing.
function Get-CertificationProblems($Scans) {
    $p = [System.Collections.Generic.List[string]]::new()
    foreach ($sc in $Scans) {
        if ($sc.hits -gt 0) { $p.Add("$($sc.hits) object(s) under $($sc.root) still carry a Codex SID, e.g. $($sc.firstHits -join '; ')") }
        if ((Test-Gate 'scan-complete') -and ($sc.foldersLeftUnscanned -gt 0 -or $sc.unreadable -gt 0)) {
            $p.Add("scan of $($sc.root) cannot certify the tree: $($sc.scanned) objects read, $($sc.unreadable) unreadable, $($sc.foldersLeftUnscanned) folders left at the time cap (raise -ScanSeconds)")
        }
    }
    return @($p)
}

function Invoke-TreeScans($Spec, [int]$Seconds, $Before = $null) {
    $sids = Get-ScanSids $Spec; $drop = Get-PurgeSids $Spec
    $scans = @()
    foreach ($t in $Spec.AclTargets) {
        if (-not $t.Scan -or -not (Test-Path -LiteralPath $t.Path)) { continue }
        $scans += Find-SidAcesDeep $t.Path $sids $Seconds $null $Before $drop
    }
    return $scans
}

# Pre-change snapshot of every scanned object's list: kept in memory for the read-back, and written to the protected
# backup folder (with its hash) for undo. Refuses when it is incomplete or finds something this script must not touch.
function Write-TreeSnapshot($Spec, [string]$Path, [int]$Seconds) {
    $sids = Get-ScanSids $Spec; $purge = Get-PurgeSids $Spec
    $exempt = @{}; foreach ($t in $Spec.AclTargets) { $exempt["$($t.Path)|$($t.Sid)"] = $true }
    $pre = @{ Purge = $purge; Exempt = $exempt }
    $collect = [System.Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    $w = [IO.StreamWriter]::new($Path, $false, [Text.UTF8Encoding]::new($false))
    $scans = @()
    try {
        foreach ($t in $Spec.AclTargets) {
            if (-not $t.Scan -or -not (Test-Path -LiteralPath $t.Path)) { continue }
            $scans += Find-SidAcesDeep $t.Path $sids $Seconds $w $null @() $pre $collect
        }
    } finally { $w.Dispose() }
    $lines = 0; foreach ($l in [IO.File]::ReadLines($Path)) { $lines++ }
    $expected = 0; foreach ($sc in $scans) { $expected += $sc.scanned + $sc.unreadable }
    $cut = @($scans | Where-Object { $_.foldersLeftUnscanned -gt 0 }).Count
    if ((Test-Gate 'tree-snapshot') -and ($lines -ne $expected -or $cut)) {
        Refuse 'tree-snapshot' "the before-change snapshot of the access lists is incomplete ($lines lines, $expected objects, $cut trees cut by the time limit); raise -SnapshotSeconds"
    }
    $unread = @($scans | ForEach-Object { $_.firstUnreadable })
    $unreadN = 0; foreach ($sc in $scans) { $unreadN += $sc.unreadable }
    if ($unreadN -and (Test-Gate 'snapshot-unreadable')) {
        Refuse 'snapshot-unreadable' "$unreadN object(s) cannot be read, so their access lists cannot be recorded or checked afterwards (first: $($unread -join '; ')); nothing was changed"
    }
    $below = @($scans | ForEach-Object { $_.explicitCodex })
    if ($below.Count -and (Test-Gate 'codex-below-root')) {
        Refuse 'codex-below-root' "$($below.Count) explicit entr(ies) for a Codex capability SID sit below the folders' own entries, where none were recorded (first: $(($below | Select-Object -First 5) -join '; ')); nothing was changed"
    }
    $foreign = @($scans | ForEach-Object { $_.hitSids } | Where-Object { $_ -and $purge -cnotcontains $_ } | Select-Object -Unique)
    if ($foreign.Count -and (Test-Gate 'scan-only-sid')) {
        Refuse 'scan-only-sid' "access entries naming $($foreign -join ', ') exist in the scanned trees; this script does not remove them, so it stops before changing anything"
    }
    $emptied = @($scans | ForEach-Object { $_.emptyAfter })
    if ($emptied.Count -and (Test-Gate 'empty-after')) {
        Refuse 'empty-after' "$($emptied.Count) object(s) carry only Codex entries, so cutting them out would leave an empty access list (first: $(($emptied | Select-Object -First 5) -join '; ')); nothing was changed"
    }
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
    [IO.File]::WriteAllText("$Path.meta.json", ([ordered]@{ sha256 = $sha; lines = $lines; written = (Get-Date).ToString('o') } | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    return [ordered]@{ lines = $lines; scans = $scans; before = $collect; sha256 = $sha }
}

function Read-TreeSnapshot([string]$Path) {
    $h = [System.Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($l in [IO.File]::ReadLines($Path)) {
        $i = $l.IndexOf("`t")
        if ($i -lt 1 -or $l.StartsWith('!unreadable')) { continue }
        $h[$l.Substring(0, $i)] = Get-Interned $l.Substring($i + 1)
    }
    return $h
}

# ---------------------------------------------------------------- orchestration

function Get-StepAbsent($Spec, $State, $Step) {
    switch ($Step.kind) {
        'acl' { return (($State.acl | Where-Object { $_.id -ceq $Step.id }).aces.Count -eq 0) }
        'disable' { $u = $State.users | Where-Object { $_.name -ceq $Step.target }; return (-not $u.exists) -or ($u.enabled -eq $false) }
        'firewall' { return (($State.firewall | Where-Object { $_.displayName -ceq $Step.target }).count -eq 0) }
        'registry' { $n = ($Step.target -split ' :: ')[1]; return ($null -eq $State.registry.targets[$n]) }
        'user' { return (-not ($State.users | Where-Object { $_.name -ceq $Step.target }).exists) }
        'group' { return (-not $State.group.exists) }
        default { return $false }
    }
}

function Invoke-Step($Spec, $Step) {
    if ($script:SelfTestActive -and $script:StepFault) { & $script:StepFault $Step }
    switch ($Step.kind) {
        'acl' { Remove-SidAcesTree $Spec $Step.target $script:AclRemovalSeconds }
        'firewall' { Remove-AllowedFirewallRule $Spec $Step.target }
        'registry' { Remove-AllowedRegistryValue $Spec (($Step.target -split ' :: ')[1]) }
        'disable' { Disable-AllowedUser $Spec $Step.target }
        'user' { Remove-AllowedUser $Spec $Step.target }
        'group' { Remove-AllowedGroup $Spec $Step.target }
    }
}

function Write-Plan($Spec, $State, $Plan, $Findings, [string]$Digest, [string]$Stage = 'All') {
    Write-Host ''
    Write-Host 'PLAN: remove the Codex sandbox leftovers (current state -> target state)' -ForegroundColor Cyan
    Write-Host ("STAGE: $Stage" + $(if ((Test-StageHas $Stage 'Accounts') -and -not (Test-StageHas $Stage 'Acl')) { ' (firewall rules, hidden-user values, accounts and group; no access list is read or changed)' } else { '' }))
    foreach ($s in $Plan) {
        $now = if ($s.present) { 'PRESENT' } else { 'already gone' }
        $after = if ($s.present) { 'REMOVED' } else { 'unchanged' }
        Write-Host ("  [{0,-3}] {1,-9} {2}" -f $s.id, $s.kind, $s.target)
        Write-Host ("        now: {0}   after: {1}   ({2}; {3})" -f $now, $after, $s.what, $(if ($s.reversible) { 'undoable from backup' } else { 'NOT undoable' }))
    }
    $other = @($State.registry.values.Keys | Where-Object { $Spec.Registry.Names -cnotcontains $_ })
    Write-Host ''
    Write-Host 'WILL NOT TOUCH:' -ForegroundColor Cyan
    Write-Host "  * other values in the hidden-user registry key: $(if ($other.Count) { $other -join ', ' } else { '(none present)' })"
    Write-Host '  * every other account, group, firewall rule, task and service (including blarai-coder and its firewall rule)'
    Write-Host "  * everything under $($Spec.ReportOnly) (your Codex files). Top level, left in place:"
    if (Test-Path -LiteralPath $Spec.ReportOnly) {
        Get-ChildItem -LiteralPath $Spec.ReportOnly -Force | ForEach-Object { Write-Host ("      {0}{1}" -f $_.Name, $(if ($_.PSIsContainer) { '\' } else { " ($($_.Length) bytes)" })) }
        Write-Host '    cap_sid is the one worth deleting yourself AFTER this runs; auth.json is Codex''s sign-in token.'
    }
    if (-not $State.heavy.checked) { Write-Host ''; $State.heavy.notRun | ForEach-Object { Write-Host "NOT CHECKED: $_" -ForegroundColor Yellow }; Write-Host 'An apply refuses while any check cannot run.' -ForegroundColor Yellow }
    if (Test-StageHas $Stage 'Acl') {
    Write-Host ''
    Write-Host 'WHAT THE ACCESS-ENTRY STEPS DO:' -ForegroundColor Cyan
    Write-Host '  * Every object under the BlarAI folder, Temp and C:\ovms is opened once; its access list is read, the entries naming the Codex capability SIDs are cut'
    Write-Host '    out of that exact list, and the list is written back through the same handle otherwise unchanged: same order, same inherited flags, same protection.'
    Write-Host '  * Windows is NOT asked to recompute or re-propagate anything. So no other principal gains or loses access on any object, stale inherited copies stay as they are,'
    Write-Host '    and no folder (C:\ovms included) starts or stops inheriting from its parent.'
    Write-Host '  * Before the first change the list of every object is recorded (tree-snapshot.tsv in a SYSTEM/Administrators-only backup folder). Afterwards every object is read'
    Write-Host '    back and compared with it; any difference other than the removed entries stops the run before the irreversible steps. -RestoreAcl puts the lists back exactly.'
    Write-Host '  * An object that would be left with an empty list, a file with more than one name (hard link), an object that resolves outside its folder (a link swapped in)'
    Write-Host '    or one that cannot be read is NOT changed, and the run stops. An earlier unfinished apply must be resumed (-ResumeFrom) so its changes stay visible.'
    Write-Host '  * Temp holds live files of running programs: close Claude, Codex and other sessions first.'
    Write-Host "  * A hard-linked file has one shared list; it is edited once if every name is inside these folders or under the LA-approved link folder(s): $((@($Spec.LinkRoots | Where-Object { $_ }) -join '; '))"
    foreach ($a in @($State.acl | Where-Object { $_.exists })) {
        Write-Host "  * $($a.path): entries to remove from its own list: $(if ($a.aces.Count) { $a.aces -join ' ' } else { '(none present)' })"
    }
    } else {
        Write-Host ''
        Write-Host 'NOT PART OF THIS STAGE: the four access-entry steps (BlarAI folder, its .git, Temp, C:\ovms). They are a separate stage and are not read or changed here.' -ForegroundColor Cyan
    }
    Write-Host ''
    Write-Host 'IF CODEX IS RUN AGAIN:' -ForegroundColor Cyan
    Write-Host '  * Its elevated setup recreates the accounts, the group, the firewall rules and the hidden-user values.'
    if (Test-StageHas $Stage 'Acl') { Write-Host '  * Its sandbox re-adds capability-SID entries on the BlarAI folder and Temp; with cap_sid kept they are the same SIDs as today.' }
    Write-Host '  * Nothing here blocks that. Delete cap_sid (and auth.json) after this run if Codex should not come back.'
    Write-Host ''
    if ($Findings.Count) {
        Write-Host 'UNEXPECTED STATE. Apply will refuse and change nothing until these are looked at:' -ForegroundColor Red
        $Findings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    } else { Write-Host 'No unexpected state found.' -ForegroundColor Green }
    Write-Host ''
    Write-Host "Plan digest: $Digest"
}

function Invoke-DryRun($Spec, [bool]$IsAdmin, [string]$Stage = 'All') {
    $state = Get-LiveState $Spec $IsAdmin $true $Stage
    $find = Get-Findings $Spec $state
    $plan = Get-Plan $Spec $state $Stage
    $digest = Get-PlanDigest $Spec $plan $Stage
    return [ordered]@{ State = $state; Findings = $find; Plan = $plan; Digest = $digest }
}

function Invoke-Apply {
    param($Spec, [string]$ExpectPlan, [string]$BackupRoot, [bool]$IsAdmin = (Test-Elevated), [int]$ScanSecs = 1800, [int]$SnapSecs = 1800, [string]$Stage = 'All', [string]$ResumeFrom = '')
    $hasAcl = $false
    $res = [ordered]@{ ok = $false; code = 2; message = ''; steps = @(); backupDir = $null; digest = $null; verdict = $null; scans = @(); collateral = @(); certified = $false; resumedFrom = $null; missing = 0; stoppedBeforeIrreversible = $false }
    $baseline = $null
    try {
        Assert-Elevated $IsAdmin
        $hasAcl = Test-StageHas $Stage 'Acl'
        if ($hasAcl -and ($Spec.Mode -ceq 'real') -and (Test-Gate 'acl-stage-blocked')) {
            Refuse 'acl-stage-blocked' 'the access-entry stage is not enabled for the real machine; run -Stage Accounts'
        }
        Assert-SpecAllowed $Spec
        $pre = Invoke-DryRun $Spec $IsAdmin $Stage
        $res.digest = $pre.Digest
        if ((Test-Gate 'empty-plan') -and $pre.Plan.Count -eq 0) { Refuse 'empty-plan' "the plan for stage '$Stage' has no steps; there is nothing to approve or apply" }
        if ($pre.Findings.Count) { Refuse 'unexpected-live' ("unexpected state: " + ($pre.Findings -join ' | ')) }
        if (Test-Gate 'plan-digest') {
            if ([string]::IsNullOrEmpty($ExpectPlan)) { Refuse 'plan-digest' 'no -ExpectPlan given' }
            if ($ExpectPlan -cne $pre.Digest) { Refuse 'plan-digest' "the live state differs from the plan you approved (live digest $($pre.Digest))" }
        }
        $resume = $null
        if ($hasAcl) { $resume = Resolve-ResumeBaseline $Spec $BackupRoot $ResumeFrom }
        $script:LastSnapshot = $null
        $res.backupDir = Write-Backup $Spec $pre.State $pre.Digest $BackupRoot $SnapSecs $Stage
        if ($hasAcl) {
            if ($null -eq $script:LastSnapshot) { throw 'the before-change snapshot is missing' }
            $baseline = if ($resume) { $resume.before } else { $script:LastSnapshot.before }
            if ($resume) { $res.resumedFrom = $resume.dir }
        }
        Write-Host "Backup written and read back: $($res.backupDir)" -ForegroundColor Green
    } catch {
        $res.message = $_.Exception.Message
        return $res
    }
    $res.code = 0
    $cert = @(); $left = @()
    # Runs steps in order; the first failure stops the run (earlier steps done, later untouched).
    $runSteps = {
        param($steps)
        foreach ($s in $steps) {
            if ($res.code -ne 0) { break }
            if (-not $s.present) { $res.steps += [ordered]@{ id = $s.id; target = $s.target; result = 'already gone' }; continue }
            try {
                Write-Host ("  removing [{0}] {1}: {2} ..." -f $s.id, $s.kind, $s.target)
                Invoke-Step $Spec $s
                $now = Get-LiveState $Spec $IsAdmin $false $Stage
                if (-not $script:SimulateOnly -and -not (Get-StepAbsent $Spec $now $s)) { throw "step [$($s.id)] $($s.target) is still present after removal" }
                $res.steps += [ordered]@{ id = $s.id; target = $s.target; result = 'removed' }
            } catch {
                $res.steps += [ordered]@{ id = $s.id; target = $s.target; result = "FAILED: $($_.Exception.Message)" }
                $res.message = "Stopped at [$($s.id)] $($s.target): $($_.Exception.Message). Earlier steps are done; later steps were not touched."
                $res.code = 3
            }
        }
    }
    try {
        # 1. The access lists: the Codex entries are cut out of each object's own list; nothing else is touched.
        $script:AclRemovalSeconds = $SnapSecs
        & $runSteps @($pre.Plan | Where-Object { $_.kind -ceq 'acl' })
        if ($hasAcl -and $script:SelfTestActive -and $script:AfterRemovalHook) { & $script:AfterRemovalHook }
        # 2. Read every object back and compare with its before-change list, before anything irreversible happens.
        if ($hasAcl -and $res.code -eq 0 -and -not $script:SimulateOnly) {
            Write-Host '  checking every object in the BlarAI folder, Temp and C:\ovms ...'
            $res.scans = @(Invoke-TreeScans $Spec $ScanSecs $baseline)
            $cert = @(Get-CertificationProblems $res.scans)
            $res.collateral = @($res.scans | ForEach-Object { $_.collateral })
            $res.missing = 0; foreach ($sc in $res.scans) { $res.missing += $sc.missingNow }
            if ($res.collateral.Count) {
                Set-Content -LiteralPath (Join-Path $res.backupDir 'collateral.txt') -Value $res.collateral -Encoding UTF8
                if (Test-Gate 'collateral-stop') { $cert += "an access list changed in a way other than cutting out the Codex entries on $($res.collateral.Count) object(s) (collateral.txt in the backup folder; first: $($res.collateral[0]))" }
            }
            $res.certified = ($cert.Count -eq 0)
            if ($cert.Count) {
                $res.code = 1
                $res.stoppedBeforeIrreversible = $true
                $res.message = 'Stopped before the irreversible steps (firewall rules, hidden-user values, accounts and group were NOT touched). Every list can be restored exactly from the backup folder (-RestoreAcl). ' + ($cert -join ' | ')
            }
        }
        # 3. The irreversible steps, last.
        if ($res.code -eq 0) { & $runSteps @($pre.Plan | Where-Object { $_.kind -cne 'acl' }) }
    } catch {
        $res.code = 3
        $res.message = "Unexpected error: $($_.Exception.Message). Earlier steps may be done; see the steps list."
    }
    try {
        $final = Get-LiveState $Spec $IsAdmin $false $Stage
        $left = @($pre.Plan | Where-Object { -not (Get-StepAbsent $Spec $final $_) } | ForEach-Object { "[$($_.id)] $($_.target)" })
    } catch {
        $left = @("the final state could not be read: $($_.Exception.Message)")
        if ($res.code -eq 0) { $res.code = 3; $res.message = 'The final state could not be read, so the result is unverified.' }
    }
    $res.ok = Get-ApplyVerdict $res.code $left $cert
    $res.verdict = if ($res.ok) { 'PASS' } else { 'FAIL' }
    if ($res.code -eq 0 -and $left.Count) { $res.code = 1; $res.message = 'Still present after apply: ' + ($left -join '; ') }
    $report = [ordered]@{ verdict = $res.verdict; code = $res.code; message = $res.message; stage = $Stage; planDigest = $pre.Digest; steps = $res.steps; stillPresent = $left; certification = $cert; stoppedBeforeIrreversible = $res.stoppedBeforeIrreversible
        resumedFrom = $res.resumedFrom; objectsMissingAtReadback = $res.missing
        scans = @($res.scans | ForEach-Object { [ordered]@{ root = $_.root; scanned = $_.scanned; unreadable = $_.unreadable; vanished = $_.vanished; hits = $_.hits; foldersLeftUnscanned = $_.foldersLeftUnscanned; objectsNotInSnapshot = $_.notInBefore; objectsMissingNow = $_.missingNow; seconds = $_.seconds } })
        collateralCount = $res.collateral.Count; collateralFirst = @($res.collateral | Select-Object -First 50); finishedAt = (Get-Date).ToString('o') }
    try { ($report | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath (Join-Path $res.backupDir 'report.json') -Encoding UTF8 }
    catch { Write-Host "Could not write report.json: $($_.Exception.Message)" -ForegroundColor Red }
    if ($res.ok -and $res.resumedFrom) {
        try { Set-Content -LiteralPath (Join-Path $res.resumedFrom 'resolved.txt') -Value "resolved by $($res.backupDir) at $((Get-Date).ToString('o'))" -Encoding UTF8 } catch { Write-Host "Could not mark the earlier run resolved: $($_.Exception.Message)" -ForegroundColor Yellow }
    }
    return $res
}

function Invoke-VerifyRun($Spec, [bool]$IsAdmin, [int]$ScanSecs, [string]$Stage = 'All') {
    $d = Invoke-DryRun $Spec $IsAdmin $Stage
    $scans = @(if (Test-StageHas $Stage 'Acl') { Invoke-TreeScans $Spec $ScanSecs })
    $problems = @(Get-VerifyProblems $d.Plan $d.Findings $scans $Stage)
    return [ordered]@{ ok = ($problems.Count -eq 0); problems = $problems; scans = $scans; notes = @() }
}

# ---------------------------------------------------------------- self-test

function New-Fixture([string]$Tag) {
    $pf = $script:Own
    $root = "$($script:ThrowRoot)\$pf" + "st-$Tag"
    $ua = "$pf" + "ua-$Tag"; $ub = "$pf" + "ub-$Tag"; $grp = "$pf" + "grp-$Tag"
    $pw = ConvertTo-SecureString ([guid]::NewGuid().ToString('N') + 'Aa1!') -AsPlainText -Force
    foreach ($n in $ua, $ub) { New-LocalUser -Name $n -Password $pw -Disabled | Out-Null; $script:Created.Add("user:$n") }
    New-LocalGroup -Name $grp -Description "zz1740 fixture group (managed)" | Out-Null; $script:Created.Add("group:$grp")
    Add-LocalGroupMember -Group $grp -Member $ua, $ub
    $sidA = (Get-LocalUser $ua).SID.Value; $sidB = (Get-LocalUser $ub).SID.Value; $sidG = (Get-LocalGroup $grp).SID.Value
    $fwNames = @()
    foreach ($proto in 'tcp', 'udp') {
        $dn = "$pf" + "fw-$Tag-$proto"; $id = "$pf" + "fwid-$Tag-$proto"
        $rp = if ($proto -eq 'tcp') { @{ RemotePort = '1-65535' } } else { @{} }
        New-NetFirewallRule -Name $id -DisplayName $dn -Direction Outbound -Action Block -Protocol $proto.ToUpper() -RemoteAddress '127.0.0.0/8' -LocalUser "D:(A;;CC;;;$sidA)" -Enabled False @rp | Out-Null
        $script:Created.Add("fw:$id"); $fwNames += [ordered]@{ DisplayName = $dn; Name = $id; UserSid = $sidA }
    }
    $by = "$($pf)by-$Tag"; $keep = "$($pf)keepme"
    New-NetFirewallRule -Name $by -DisplayName $by -Direction Outbound -Action Block -Protocol TCP -RemoteAddress '127.0.0.0/8' -Enabled False | Out-Null
    $script:Created.Add("fw:$by")
    $regRoot = "HKCU:\Software\$pf" + "st-$Tag"
    New-Item -Path "$regRoot\UserList" -Force | Out-Null; $script:Created.Add("reg:$regRoot")
    New-ItemProperty -Path "$regRoot\UserList" -Name $ua -PropertyType DWord -Value 0 | Out-Null
    New-ItemProperty -Path "$regRoot\UserList" -Name $ub -PropertyType DWord -Value 0 | Out-Null
    New-ItemProperty -Path "$regRoot\UserList" -Name $keep -PropertyType DWord -Value 0 | Out-Null
    New-Item -Path "$regRoot\ProfileList" -Force | Out-Null
    New-Item -ItemType Directory -Path "$root\profiles" -Force | Out-Null; $script:Created.Add("dir:$root")
    $capA = 'S-1-5-21-1111111111-2222222222-3333333333-4001'; $capB = 'S-1-5-21-1111111111-2222222222-3333333333-4002'
    $otherSid = 'S-1-5-21-1111111111-2222222222-3333333333-4003'; $extraSid = 'S-1-5-21-1111111111-2222222222-3333333333-4005'
    $rw = [Security.AccessControl.FileSystemRights]0x1201bf
    $oici = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    $none = [Security.AccessControl.PropagationFlags]::None
    $addAce = { param($p, $sid, $type, $inh, $prop, $rights)
        $a = Get-Acl -LiteralPath $p
        $a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$sid, $rights, $inh, $prop, $type)); Set-Acl -LiteralPath $p -AclObject $a }
    # repo (A7-like) with a .git (A8-like)
    New-Item -ItemType Directory -Path "$root\repo\sub\deep", "$root\repo\.git\objects" -Force | Out-Null
    'x' | Set-Content "$root\repo\README.md"; 'x' | Set-Content "$root\repo\sub\deep\f.txt"; 'x' | Set-Content "$root\repo\.git\config"
    & $addAce "$root\repo" $capA 'Allow' $oici $none $rw
    & $addAce "$root\repo\.git" $capB 'Deny' ([Security.AccessControl.InheritanceFlags]::None) $none ([Security.AccessControl.FileSystemRights]0x130156)
    & $addAce "$root\repo\.git" $capB 'Deny' ([Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit') ([Security.AccessControl.PropagationFlags]'InheritOnly,NoPropagateInherit') ([Security.AccessControl.FileSystemRights]0x130156)
    # temp (A9-like)
    # built under a parent that grants an unrelated (app-container-shaped) principal, then moved: the entries on the
    # root are inherited copies that the new parent does not hand down, as on the real Temp folder
    $staleSid = 'S-1-15-3-111-222-333-444-555-666-777'
    New-Item -ItemType Directory -Path "$root\pt\temp\claude\x" -Force | Out-Null; 'x' | Set-Content "$root\pt\temp\claude\x\f.tmp"
    & $addAce "$root\pt" $staleSid 'Allow' ([Security.AccessControl.InheritanceFlags]::None) $none ([Security.AccessControl.FileSystemRights]0x1f01ff)
    $ptAcl = Get-Acl -LiteralPath "$root\pt"; $ptSd = $ptAcl.GetSecurityDescriptorSddlForm('Access'); $ptAcl.SetSecurityDescriptorSddlForm($ptSd.Insert($ptSd.IndexOf('('), "(A;OICIIO;GA;;;$staleSid)"), 'Access'); Set-Acl -LiteralPath "$root\pt" -AclObject $ptAcl
    & $addAce "$root\pt\temp" $capB 'Allow' $oici $none $rw
    Move-Item -LiteralPath "$root\pt\temp" -Destination "$root\temp"
    Remove-Item -LiteralPath "$root\pt" -Recurse -Force
    # a folder moved in from a parent that granted an unrelated principal: its inherited copy of that entry is stale
    New-Item -ItemType Directory -Path "$root\p3\mv" -Force | Out-Null; 'x' | Set-Content "$root\p3\mv\f.txt"
    & $addAce "$root\p3" $otherSid 'Allow' $oici $none $rw
    [IO.File]::WriteAllText('\\?\' +"$root\p3\mv\dot.", 'x')
    Move-Item -LiteralPath "$root\p3\mv" -Destination "$root\temp\mv"
    Remove-Item -LiteralPath "$root\p3" -Recurse -Force
    # ovms (A10-like): stale inherited copy, parent without the entry
    New-Item -ItemType Directory -Path "$root\p1\ovms\bin", "$root\p2" -Force | Out-Null; 'x' | Set-Content "$root\p1\ovms\bin\a.dll"
    # p1 does not inherit, so what it hands down lacks what the folder it is moved into hands down (as C:\ovms lacks C:\'s entries)
    $p1Acl = Get-Acl -LiteralPath "$root\p1"; $p1Acl.SetAccessRuleProtection($true, $false)
    $p1Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User, [Security.AccessControl.FileSystemRights]::FullControl, $oici, $none, 'Allow'))
    Set-Acl -LiteralPath "$root\p1" -AclObject $p1Acl
    & $addAce "$root\p1" $capB 'Allow' $oici $none $rw
    Move-Item -LiteralPath "$root\p1\ovms" -Destination "$root\ovms"
    Remove-Item -LiteralPath "$root\p1", "$root\p2" -Recurse -Force
    # owner is Administrators (as on the real folder); only the owner section is written
    $odi = [IO.DirectoryInfo]"$root\ovms"
    $oa = [IO.FileSystemAclExtensions]::GetAccessControl($odi, [Security.AccessControl.AccessControlSections]::Owner)
    $oa.SetOwner([Security.Principal.NTAccount]'BUILTIN\Administrators')
    [IO.FileSystemAclExtensions]::SetAccessControl($odi, $oa)
    # report-only folder
    New-Item -ItemType Directory -Path "$root\dotcodex" -Force | Out-Null; 'secret' | Set-Content "$root\dotcodex\auth.json"
    $spec = [ordered]@{
        Mode = 'test'
        Users = @([ordered]@{ Name = $ua; Sid = $sidA }, [ordered]@{ Name = $ub; Sid = $sidB })
        Group = [ordered]@{ Name = $grp; Sid = $sidG; Description = 'zz1740 fixture group (managed)' }
        Firewall = $fwNames
        FirewallGlob = "$pf" + "fw-$Tag"
        ServiceGlob = "$pf" + "st-$Tag"
        Registry = [ordered]@{ Path = "$regRoot\UserList"; Names = @($ua, $ub) }
        ProfileListRoot = "$regRoot\ProfileList"
        ProfileFolderRoot = "$root\profiles"
        WfpNeedles = @("$pf" + "st-$Tag")
        AclTargets = @(
            [ordered]@{ Id = 'A8'; Path = "$root\repo\.git"; Sid = $capB; Scan = $false },
            [ordered]@{ Id = 'A7'; Path = "$root\repo"; Sid = $capA; Scan = $true },
            [ordered]@{ Id = 'A9'; Path = "$root\temp"; Sid = $capB; Scan = $true },
            [ordered]@{ Id = 'A10'; Path = "$root\ovms"; Sid = $capB; Scan = $true })
        ReportOnly = "$root\dotcodex"
        ExtraScanSids = @($extraSid)
        LinkRoots = @()
    }
    return [ordered]@{ Tag = $Tag; Root = $root; Spec = $spec; Ua = $ua; Ub = $ub; Group = $grp; CapA = $capA; CapB = $capB; StaleSid = $staleSid; OtherSid = $otherSid; ExtraSid = $extraSid; Bystander = $by; Keep = $keep; RegRoot = $regRoot }
}

function Remove-Throwaway([switch]$All) {
    # Cleanup touches only this run's own objects (all zz1740- ones with -All); never anything else.
    $pf = if ($All) { $script:Pfx } else { $script:Own }; $removed = [System.Collections.Generic.List[string]]::new(); $failed = [System.Collections.Generic.List[string]]::new()
    $try = { param($what, $sb) try { & $sb; $removed.Add($what) } catch { $failed.Add("$what : $($_.Exception.Message)") } }
    foreach ($r in @(Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith($pf, 'Ordinal') -or $_.DisplayName.StartsWith($pf, 'Ordinal') })) {
        $n = $r.Name; if ($n.StartsWith($pf, 'Ordinal')) { & $try "firewall rule $n" { Remove-NetFirewallRule -Name $n } }
    }
    foreach ($g in @(Get-LocalGroup -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith($pf, 'Ordinal') })) { $n = $g.Name; & $try "group $n" { Remove-LocalGroup -Name $n } }
    foreach ($u in @(Get-LocalUser -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith($pf, 'Ordinal') })) { $n = $u.Name; & $try "user $n" { Remove-LocalUser -Name $n } }
    foreach ($k in @(Get-ChildItem 'HKCU:\Software' -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName.StartsWith($pf, 'Ordinal') })) { $p = $k.PSPath; & $try "registry key $($k.PSChildName)" { Remove-Item -LiteralPath $p -Recurse -Force } }
    foreach ($d in @(Get-ChildItem $script:ThrowRoot -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith($pf, 'Ordinal') })) {
        $p = $d.FullName
        if (-not (Test-UnderThrowRoot $p)) { continue }
        & $try "folder $p" {
            Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | ForEach-Object { [IO.Directory]::Delete($_.FullName) }
            Remove-Item -LiteralPath ('\\?\' + $p) -Recurse -Force
        }
    }
    return [ordered]@{ removed = @($removed); failed = @($failed) }
}

function Invoke-SelfTest {
    $script:SelfTestActive = $true
    $ownWas = $script:Own
    $pdWas = $env:ProgramData
    $script:Own = 'zz1740-' + [guid]::NewGuid().ToString('N').Substring(0, 4) + '-'
    $adminTempWas = $script:AdminTempRoot
    $script:AdminTempRoot = "$($script:ThrowRoot)\$($script:Own)admintmp"
    $script:Created = [System.Collections.Generic.List[string]]::new()
    $results = [System.Collections.Generic.List[object]]::new()
    $T = { param($name, $sb) try { $r = & $sb; $ok = (@($r)[-1] -eq $true); $results.Add([ordered]@{ test = $name; pass = $ok; detail = $(if ($ok) { '' } else { "returned: $r" }) }) } catch { $results.Add([ordered]@{ test = $name; pass = $false; detail = "threw: $($_.Exception.Message)" }) } }
    # Expect a REFUSED[gate] throw; false if it does not throw or the gate differs.
    $Refused = { param($gate, $sb) try { & $sb | Out-Null; return $false } catch { return ($_.Exception.Message -like "REFUSED``[$gate``]*") } }
    $With = { param($gates, $sb) $script:GatesOff = @($gates); try { & $sb } finally { $script:GatesOff = @() } }
    $exists = @{
        user = { param($n) [bool](Get-LocalUser -Name $n -ErrorAction SilentlyContinue) }
        group = { param($n) [bool](Get-LocalGroup -Name $n -ErrorAction SilentlyContinue) }
        fw = { param($n) [bool](Get-NetFirewallRule -Name $n -ErrorAction SilentlyContinue) }
    }
    $real = Get-RealSpec
    try {
        $null = Remove-Throwaway
        $bk = "$($script:ThrowRoot)\$($script:Own)backups"; New-Item -ItemType Directory $bk -Force | Out-Null
        $bkW = "$($script:ThrowRoot)\$($script:Own)backups-w"; New-Item -ItemType Directory $bkW -Force | Out-Null

        # ---- pure helpers
        & $T 'pin: real spec hashes to the pinned digest' { (Get-SpecDigest $real) -ceq $script:RealSpecPin }
        & $T 'digest: stable across calls' { (Get-SpecDigest $real) -ceq (Get-SpecDigest (Get-RealSpec)) }
        & $T 'digest: changes when a name changes' { $m = Get-RealSpec; $m.Users[0].Name = 'x'; (Get-SpecDigest $m) -cne $script:RealSpecPin }
        & $T 'real spec lists exactly the recorded objects' { ($real.Users.Count -eq 2) -and ($real.Firewall.Count -eq 2) -and ($real.AclTargets.Count -eq 4) -and ($real.Registry.Names.Count -eq 2) }
        & $T 'elevation gate blocks' { & $Refused 'elevation' { Assert-Elevated $false } }
        & $T 'elevation gate: toggle off lets it through (mutation)' { & $With @('elevation') { Assert-Elevated $false; $true } }
        & $T 'elevation gate: admin passes' { Assert-Elevated $true; $true }
        & $T 'stage: Accounts covers the account steps only, AclEntries the access entries only, All both' { (Test-StageHas 'Accounts' 'Accounts') -and -not (Test-StageHas 'Accounts' 'Acl') -and (Test-StageHas 'AclEntries' 'Acl') -and -not (Test-StageHas 'AclEntries' 'Accounts') -and (Test-StageHas 'All' 'Acl') -and (Test-StageHas 'All' 'Accounts') }
        $sid7 = 'S-1-5-21-1-2-3-1007'
        & $T 'fw scope: exactly the one SID passes' { Test-ScopeOnlySid "O:LSD:(A;;CC;;;$sid7)" $sid7 }
        & $T 'fw scope: a longer SID that starts the same is not a match' { -not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$($sid7)0)" $sid7) }
        & $T 'fw scope: a second SID in the scope is not a match' { -not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$sid7)(A;;CC;;;S-1-5-21-1-2-3-1009)" $sid7) }
        & $T 'fw scope: no SID at all is not a match' { -not (Test-ScopeOnlySid '' $sid7) }
        & $T 'fw scope: a shorthand principal (WD, BU), a deny entry or two entries of any form is not a match' { $s9 = 'S-1-5-21-1-2-3-1007'; (-not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;WD)" $s9)) -and (-not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s9)(A;;CC;;;BU)" $s9)) -and (-not (Test-ScopeOnlySid "O:LSD:(D;;CC;;;$s9)" $s9)) -and (-not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s9)(D;;CC;;;WD)" $s9)) -and (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s9)" $s9) }
        $rsid = $real.Users[0].Sid
        & $T 'rights: a SID in the export is found' { (Find-RightsHits $real "SeBackupPrivilege = *S-1-5-32-544,*$rsid").Count -ge 1 }
        & $T 'rights: a local account listed by NAME (as secedit writes it) is found' { (Find-RightsHits $real 'SeInteractiveLogonRight = *S-1-5-32-544,CodexSandboxOffline,Guest').Count -ge 1 }
        & $T 'rights: by-name lookup off (mutation) is blind to the name' { & $With @('rights-by-name') { (Find-RightsHits $real 'SeInteractiveLogonRight = *S-1-5-32-544,CodexSandboxOffline,Guest').Count -eq 0 } }
        & $T 'rights: an export of other principals has no hit' { (Find-RightsHits $real 'SeInteractiveLogonRight = *S-1-5-32-544,blarai-coder,Guest').Count -eq 0 }
        $aceOld = 'D:PAI(A;OICI;FA;;;SY)(A;OICIID;0x1201bf;;;S-1-5-21-1-2-3-4001)(A;OICIID;0x1201bf;;;S-1-5-21-1-2-3-4003)'
        & $T 'ace delta: only the dropped SID differs, so nothing is reported' { $null -eq (Get-AceDelta $aceOld 'D:PAI(A;OICI;FA;;;SY)(A;OICIID;0x1201bf;;;S-1-5-21-1-2-3-4003)' @('S-1-5-21-1-2-3-4001')) }
        & $T 'ace delta: another principal lost its entry, so it is reported' { (Get-AceDelta $aceOld 'D:PAI(A;OICI;FA;;;SY)' @('S-1-5-21-1-2-3-4001')) -like '*4003*' }
        & $T 'ace delta: with no drop list the Codex SID shows as a difference (mutation)' { $null -ne (Get-AceDelta $aceOld 'D:PAI(A;OICI;FA;;;SY)(A;OICIID;0x1201bf;;;S-1-5-21-1-2-3-4003)' @()) }
        & $T 'scan SIDs: the real set holds the readonly capability SID and the account and group SIDs' { $ss = Get-ScanSids $real; ($ss -ccontains $real.ExtraScanSids[0]) -and ($ss -ccontains $real.Users[0].Sid) -and ($ss -ccontains $real.Group.Sid) -and ($ss.Count -eq 6) }
        & $T 'scan SIDs: the purge set stays the two capability SIDs of the access targets' { (Get-PurgeSids $real).Count -eq 2 }
        & $T 'scan SIDs: with the all-SIDs lock off (mutation) the scan is blind to the extra ones' { & $With @('scan-all-sids') { (Get-ScanSids $real).Count -eq 2 } }
        $good = [ordered]@{ root = 'x'; hits = 0; firstHits = @(); foldersLeftUnscanned = 0; unreadable = 0; scanned = 5 }
        $cut = [ordered]@{ root = 'x'; hits = 0; firstHits = @(); foldersLeftUnscanned = 3; unreadable = 0; scanned = 5 }
        $unr = [ordered]@{ root = 'x'; hits = 0; firstHits = @(); foldersLeftUnscanned = 0; unreadable = 2; scanned = 5 }
        $hit = [ordered]@{ root = 'x'; hits = 1; firstHits = @('p'); foldersLeftUnscanned = 0; unreadable = 0; scanned = 5 }
        $px = 'S-1-5-21-1-2-3-4010'; $py = 'S-1-5-21-1-2-3-4011'
        $parentL = "D:(A;OICI;FA;;;$px)"
        & $T 'explicit codex: an explicit entry is seen, an inherited one is not' { ((Get-ExplicitPurgeSids "D:(A;OICI;FA;;;$px)" @($px)).Count -eq 1) -and ((Get-ExplicitPurgeSids "D:AI(A;OICIID;FA;;;$py)" @($py)).Count -eq 0) }
        & $T 'certification: a complete clean scan passes' { (Get-CertificationProblems @($good)).Count -eq 0 }
        & $T 'certification: a scan cut short cannot certify' { (Get-CertificationProblems @($cut)).Count -eq 1 }
        & $T 'certification: unreadable objects cannot certify' { (Get-CertificationProblems @($unr)).Count -eq 1 }
        & $T 'certification: a hit fails' { (Get-CertificationProblems @($hit)).Count -eq 1 }
        & $T 'vanished: an object deleted mid-scan is gone, a denied one is not' { (Test-ObjectVanished ([IO.FileNotFoundException]::new('x'))) -and (Test-ObjectVanished ([System.Management.Automation.MethodInvocationException]::new('m', [IO.DirectoryNotFoundException]::new('x')))) -and -not (Test-ObjectVanished ([UnauthorizedAccessException]::new('x'))) }
        & $T 'vanished: a scan root that does not exist is counted vanished, not unreadable' { $nv = Find-SidAcesDeep "$($script:ThrowRoot)\$($script:Own)no-such-root" @('S-1-1-1') 5; ($nv.vanished -ge 1) -and ($nv.unreadable -eq 0) -and ($nv.scanned -eq 0) }
        & $T 'certification: complete-scan lock off (mutation) lets a cut scan through, a hit still fails' { & $With @('scan-complete') { ((Get-CertificationProblems @($cut)).Count -eq 0) -and ((Get-CertificationProblems @($hit)).Count -eq 1) } }

        # ---- findings are pure over state; each unexpected condition is flagged, and the flag is switchable
        $fx0 = New-Fixture 'f0'
        $st0 = Get-LiveState $fx0.Spec (Test-Elevated)
        & $T 'findings: clean fixture has none' { (Get-Findings $fx0.Spec $st0).Count -eq 0 }
        $mut = { param($edit) $s = ($st0 | ConvertTo-Json -Depth 12 | ConvertFrom-Json -AsHashtable -Depth 12); & $edit $s; $s }
        foreach ($case in @(
                @{ n = 'different SID'; e = { param($s) $s.users[0].sid = 'S-1-5-21-9-9-9-9' } },
                @{ n = 'logon record'; e = { param($s) $s.users[0].lastLogon = '2026-01-01T00:00:00Z' } },
                @{ n = 'ProfileList entry'; e = { param($s) $s.users[0].profileListEntry = $true } },
                @{ n = 'profile folder'; e = { param($s) $s.users[0].profileFolders = @('C:\x') } },
                @{ n = 'extra group member'; e = { param($s) $s.group.memberSids += 'S-1-5-21-9-9-9-5' } },
                @{ n = 'extra matching rule'; e = { param($s) $s.firewallExtra = @('other [id]') } },
                @{ n = 'wrong rule direction'; e = { param($s) $s.firewall[0].direction = 'Inbound' } },
                @{ n = 'service present'; e = { param($s) $s.heavy.services = @('svc') } },
                @{ n = 'scheduled task present'; e = { param($s) $s.heavy.tasks = @('\t') } },
                @{ n = 'WFP filter hit'; e = { param($s) $s.heavy.wfpHits = @('codex') } },
                @{ n = 'user-rights hit'; e = { param($s) $s.heavy.rightsHits = @('S-1') } },
                @{ n = 'registry value of another shape'; e = { param($s) $s.registry.targets[$fx0.Ua] = 'String:1' } },
                @{ n = 'link as ACL target'; e = { param($s) $s.acl[0].exists = $true; $s.acl[0].reparse = $true } },
                @{ n = 'a safety check that could not run'; e = { param($s) $s.heavy.checked = $false; $s.heavy.notRun = @('WFP (export produced no file)') } },
                @{ n = 'firewall scope with a second SID'; e = { param($s) $s.firewall[0].localUser = "D:(A;;CC;;;$($fx0.Spec.Users[0].Sid))(A;;CC;;;S-1-5-21-9-9-9-5)" } },
                @{ n = 'firewall scope with a longer SID that starts the same'; e = { param($s) $s.firewall[0].localUser = "D:(A;;CC;;;$($fx0.Spec.Users[0].Sid)0)" } })) {
            $c = $case
            & $T "finding fires: $($c.n)" { $m = & $mut $c.e; (Get-Findings $fx0.Spec $m).Count -ge 1 }
            & $T "finding toggle: $($c.n) silent when unexpected-live is off (mutation)" { $m = & $mut $c.e; & $With @('unexpected-live') { (Get-Findings $fx0.Spec $m).Count -eq 0 } }
        }

        # ---- the exports behind the Windows Filtering Platform and user-rights checks
        & $T 'heavy: a healthy elevated run checks both exports' { (Get-HeavyState $fx0.Spec $true).checked }
        # a read that fails is not 'already gone'
        & $T 'read errors: an account that is not there reads as absent; any other failure is thrown' { $abs = Get-LocalUserOrNull "$($script:Own)no-such-user"; function global:Get-LocalUser { throw [UnauthorizedAccessException]::new('denied') }; try { $m = try { $null = Get-LocalUserOrNull 'whoever'; '' } catch { $_.Exception.Message } } finally { Remove-Item Function:\Get-LocalUser -ErrorAction SilentlyContinue }; ($null -eq $abs) -and ($m -like '*denied*') }
        & $T 'read errors: a group that is not there reads as absent; any other failure is thrown' { $abs = Get-LocalGroupOrNull "$($script:Own)no-such-group"; function global:Get-LocalGroup { throw [UnauthorizedAccessException]::new('denied') }; try { $m = try { $null = Get-LocalGroupOrNull 'whoever'; '' } catch { $_.Exception.Message } } finally { Remove-Item Function:\Get-LocalGroup -ErrorAction SilentlyContinue }; ($null -eq $abs) -and ($m -like '*denied*') }
        & $T 'read errors: firewall rules - none found reads as empty, a real failure is thrown' { function global:Get-NetFirewallRule { [CmdletBinding()] param($DisplayName) Write-Error -Message 'No MSFT_NetFirewallRule objects found with property DisplayName' -Category ObjectNotFound }; try { $none = @(Get-FirewallRulesByDisplayName 'x') } finally { Remove-Item Function:\Get-NetFirewallRule -ErrorAction SilentlyContinue }; function global:Get-NetFirewallRule { throw [UnauthorizedAccessException]::new('denied') }; try { $m = try { $null = Get-FirewallRulesByDisplayName 'x'; '' } catch { $_.Exception.Message } } finally { Remove-Item Function:\Get-NetFirewallRule -ErrorAction SilentlyContinue }; ($none.Count -eq 0) -and ($m -like '*denied*') }
        & $T 'read errors: the state readers do not turn a failed read into an absent account' { function global:Get-LocalUser { throw [UnauthorizedAccessException]::new('denied') }; try { $m = try { $null = Get-UserState $fx0.Spec $fx0.Spec.Users[0] @(); '' } catch { $_.Exception.Message } } finally { Remove-Item Function:\Get-LocalUser -ErrorAction SilentlyContinue }; $m -like '*denied*' }
        & $T 'read errors: a service or task list that cannot be read raises a not-checked finding' { function global:Get-Service { throw [UnauthorizedAccessException]::new('denied') }; try { $hs = Get-HeavyState $fx0.Spec $true } finally { Remove-Item Function:\Get-Service -ErrorAction SilentlyContinue }; (-not $hs.checked) -and (@($hs.notRun | Where-Object { $_ -like 'services*denied*' }).Count -eq 1) }
        & $T 'heavy: non-administrator run is reported as not checked' { $h = Get-HeavyState $fx0.Spec $false; (-not $h.checked) -and $h.notRun.Count -eq 1 }
        foreach ($fault in 'wfp-missing', 'wfp-garbage', 'rights-missing', 'rights-garbage') {
            $ff = $fault
            & $T "heavy: export fault $ff is reported as not checked" { $script:ExportFault = $ff; try { $h = Get-HeavyState $fx0.Spec $true; (-not $h.checked) -and $h.notRun.Count -eq 1 } finally { $script:ExportFault = $null } }
        }
        $script:ExportFault = 'rights-garbage'
        $stNo = Get-LiveState $fx0.Spec $true
        $script:ExportFault = $null
        & $T 'heavy: a state with an export that did not run raises a finding' { (Get-Findings $fx0.Spec $stNo).Count -ge 1 }
        & $T 'heavy: plan text names the check that did not run and says an apply refuses' { $tx = (Write-Plan $fx0.Spec $stNo (Get-Plan $fx0.Spec $stNo) @(Get-Findings $fx0.Spec $stNo) 'dig' *>&1 | Out-String); $tx.Contains('NOT CHECKED: user-rights') -and $tx.Contains('refuses while any check cannot run') }
        & $T 'heavy: plan text of a healthy state has no NOT CHECKED line (probe discriminates)' { -not ((Write-Plan $fx0.Spec $st0 (Get-Plan $fx0.Spec $st0) @() 'dig' *>&1 | Out-String).Contains('NOT CHECKED')) }
        $planTxt = (Write-Plan $fx0.Spec $st0 (Get-Plan $fx0.Spec $st0) @() 'dig' *>&1 | Out-String)
        & $T 'plan text: says Codex run again re-adds capability-SID entries and recreates accounts' { $planTxt.Contains('IF CODEX IS RUN AGAIN') -and $planTxt.Contains('re-adds capability-SID entries') -and $planTxt.Contains('recreates the accounts') -and $planTxt.Contains('cap_sid') }
        & $T 'plan text: says the entries are cut out of each list through one handle, nothing re-derived, no inheritance change, the snapshot and restore' { $planTxt.Contains('cut') -and $planTxt.Contains('NOT asked to recompute or re-propagate') -and $planTxt.Contains('no folder (C:\ovms included) starts or stops inheriting') -and $planTxt.Contains('tree-snapshot.tsv') -and $planTxt.Contains('-RestoreAcl') -and $planTxt.Contains('live files') }
& $T 'plan text: lists, per folder, the entries that will be removed from its own list' { $planTxt.Contains('entries to remove from its own list') -and $planTxt.Contains($fx0.CapB) }
& $T 'plan text: names the cases that stop the run (empty list, hard link, link swapped in, unreadable) and resume' { $planTxt.Contains('empty list') -and $planTxt.Contains('hard link') -and $planTxt.Contains('link swapped in') -and $planTxt.Contains('-ResumeFrom') }
& $T 'dry run: the access-entry step state lists the entries it removes, so the plan digest binds them' { ((Get-Plan $fx0.Spec $st0 | Where-Object { $_.id -ceq 'A9' }).state -match 'aces=\[Allow') }

        # ---- allowlist and spec locks, probed with real objects but simulated destruction
        $script:SimulateOnly = $true; $script:SimLog.Clear()
        $bad = [ordered]@{ Mode = 'test'; Users = @([ordered]@{ Name = 'CodexSandboxOffline'; Sid = 'S-1-5-21-0-0-0-1' }); Group = $fx0.Spec.Group; Firewall = $fx0.Spec.Firewall; FirewallGlob = $fx0.Spec.FirewallGlob; ServiceGlob = $fx0.Spec.ServiceGlob; Registry = $fx0.Spec.Registry; ProfileListRoot = $fx0.Spec.ProfileListRoot; ProfileFolderRoot = $fx0.Spec.ProfileFolderRoot; WfpNeedles = @(); AclTargets = $fx0.Spec.AclTargets; ReportOnly = $fx0.Spec.ReportOnly }
        & $T 'spec-throwaway: test mode with CodexSandboxOffline is refused by user helper' { & $Refused 'spec-throwaway' { Remove-AllowedUser $bad 'CodexSandboxOffline' } }
        & $T 'spec-throwaway: toggle off, validator no longer objects (no action taken)' { & $With @('spec-throwaway') { Assert-SpecAllowed $bad; $true } }
        $badPath = (Copy-Spec $fx0.Spec); $badPath.AclTargets = @([ordered]@{ Id = 'X'; Path = 'C:\Users\mrbla\BlarAI'; Sid = $fx0.CapA; Scan = $false })
        & $T 'spec-throwaway: test mode with a real path is refused by the ACL helper' { & $Refused 'spec-throwaway' { Remove-SidAcesTree $badPath 'C:\Users\mrbla\BlarAI' } }
        & $T 'spec-throwaway: real firewall rule name in test mode is refused' { $b2 = (Copy-Spec $fx0.Spec); $b2.Firewall = $real.Firewall; & $Refused 'spec-throwaway' { Remove-AllowedFirewallRule $b2 'codex_sandbox_offline_block_loopback_tcp' } }
        & $T 'spec-throwaway: real registry path in test mode is refused' { $b3 = (Copy-Spec $fx0.Spec); $b3.Registry = $real.Registry; & $Refused 'spec-throwaway' { Remove-AllowedRegistryValue $b3 'CodexSandboxOffline' } }
        $mutReal = Get-RealSpec; $mutReal.Users += [ordered]@{ Name = 'someone'; Sid = 'S-1-5-21-1-1-1-1' }
        & $T 'spec-real-pinned: edited real spec is refused' { & $Refused 'spec-real-pinned' { Remove-AllowedUser $mutReal 'someone' } }
        & $T 'spec-real-pinned: toggle off, the next independent lock (selftest-no-real) still holds' { & $With @('spec-real-pinned') { & $Refused 'selftest-no-real' { Remove-AllowedUser $mutReal 'someone' } } }
        & $T 'spec-real-pinned: both off, validator no longer objects (no action taken)' { & $With @('spec-real-pinned', 'selftest-no-real') { Assert-SpecAllowed $mutReal; $true } }
        # a spec in real mode but holding fixture names only: the real accounts are never named or read here
        $fakeReal = (Copy-Spec $fx0.Spec); $fakeReal.Mode = 'real'
        & $T 'selftest-no-real: the pinned real spec itself is refused by the validator, with no account looked up' { & $Refused 'selftest-no-real' { Assert-SpecAllowed $real } }
        foreach ($k in @(
                @{ n = 'user'; sb = { Remove-AllowedUser $fakeReal $fx0.Ua } },
                @{ n = 'disable'; sb = { Disable-AllowedUser $fakeReal $fx0.Ua } },
                @{ n = 'group'; sb = { Remove-AllowedGroup $fakeReal $fx0.Group } },
                @{ n = 'firewall'; sb = { Remove-AllowedFirewallRule $fakeReal $fx0.Spec.Firewall[0].DisplayName } },
                @{ n = 'registry'; sb = { Remove-AllowedRegistryValue $fakeReal $fx0.Ua } },
                @{ n = 'acl'; sb = { Remove-SidAcesTree $fakeReal $fx0.Spec.AclTargets[3].Path } })) {
            $kk = $k
            & $T "selftest-no-real: $($kk.n) helper refuses a real-mode spec (with the pin lock off, the next independent lock holds)" { & $With @('spec-real-pinned') { & $Refused 'selftest-no-real' $kk.sb } }
        }
        & $T 'selftest-no-real: nothing reached the destructive layer' { $script:SimLog.Count -eq 0 }
        $script:SimLog.Clear()
        & $T 'selftest-no-real: both locks off, the user helper would reach the destructive layer (simulated, fixture account untouched)' {
            & $With @('spec-real-pinned', 'selftest-no-real') { Remove-AllowedUser $fakeReal $fx0.Ua }
            ($script:SimLog.Count -eq 1) -and ($script:SimLog[0] -eq "user|$($fx0.Ua)") -and (& $exists.user $fx0.Ua) }
        $script:SimLog.Clear(); $script:SimulateOnly = $false

        # ---- per-helper locks, throwaway objects only
        $fx1 = New-Fixture 'f1'; $sp = $fx1.Spec
        $nl = "$($script:Own)nl-1"; $pw = ConvertTo-SecureString ([guid]::NewGuid().ToString('N') + 'Aa1!') -AsPlainText -Force
        New-LocalUser -Name $nl -Password $pw -Disabled | Out-Null; $script:Created.Add("user:$nl")
        & $T 'name-allowlist: user not on the list is refused and survives' { (& $Refused 'name-allowlist' { Remove-AllowedUser $sp $nl }) -and (& $exists.user $nl) }
        & $T 'name-allowlist: toggle off removes it (the lock was the blocker)' { & $With @('name-allowlist') { Remove-AllowedUser $sp $nl }; -not (& $exists.user $nl) }
        $wrong = (Copy-Spec $sp); $wrong.Users = @([ordered]@{ Name = $fx1.Ua; Sid = 'S-1-5-21-9-9-9-9' }, $sp.Users[1])
        & $T 'sid-match: account with a different SID than recorded is refused and survives' { (& $Refused 'sid-match' { Remove-AllowedUser $wrong $fx1.Ua }) -and (& $exists.user $fx1.Ua) }
        & $T 'spec-wildcard: a wildcard name in the allowlist is refused' { $wc = (Copy-Spec $sp); $wc.Firewall = @([ordered]@{ DisplayName = "$($script:Own)*"; Name = 'x'; UserSid = 'x' }); & $Refused 'spec-wildcard' { Remove-AllowedFirewallRule $wc "$($script:Own)*" } }
        & $T 'spec-wildcard: a wildcard account name argument is refused' { & $Refused 'spec-wildcard' { Remove-AllowedUser $sp "$($script:Own)*" } }
        $extraU = "$($script:Own)ux-1"; New-LocalUser -Name $extraU -Password $pw -Disabled | Out-Null; $script:Created.Add("user:$extraU")
        Add-LocalGroupMember -Group $fx1.Group -Member $extraU
        & $T 'group-members: group with a foreign member is refused and survives' { (& $Refused 'group-members' { Remove-AllowedGroup $sp $fx1.Group }) -and (& $exists.group $fx1.Group) }
        & $T 'name-allowlist: group name not on the list is refused' { & $Refused 'name-allowlist' { Remove-AllowedGroup $sp "$($script:Own)other" } }
        & $T 'sid-match: group with a different SID than recorded is refused' { $wg = (Copy-Spec $sp); $wg.Group = [ordered]@{ Name = $fx1.Group; Sid = 'S-1-5-21-9-9-9-9'; Description = $sp.Group.Description }; & $Refused 'sid-match' { Remove-AllowedGroup $wg $fx1.Group } }
        & $T 'group-members: toggle off removes the group (the lock was the blocker)' { & $With @('group-members') { Remove-AllowedGroup $sp $fx1.Group }; -not (& $exists.group $fx1.Group) }
        # profile evidence for ua
        New-Item -ItemType Directory -Path "$($sp.ProfileFolderRoot)\$($fx1.Ua)" -Force | Out-Null
        & $T 'no-profile: account with a profile folder is refused and survives' { (& $Refused 'no-profile' { Remove-AllowedUser $sp $fx1.Ua }) -and (& $exists.user $fx1.Ua) }
        & $T 'no-profile: toggle off removes it (the lock was the blocker)' { & $With @('no-profile') { Remove-AllowedUser $sp $fx1.Ua }; -not (& $exists.user $fx1.Ua) }
        New-Item -ItemType Directory -Path "$($sp.ProfileListRoot)\$($sp.Users[1].Sid)" -Force | Out-Null
        & $T 'no-profile: account with a ProfileList entry is refused' { & $Refused 'no-profile' { Remove-AllowedUser $sp $fx1.Ub } }
        # firewall identity
        $badId = (Copy-Spec $sp); $badId.Firewall = @([ordered]@{ DisplayName = $sp.Firewall[0].DisplayName; Name = 'zz1740-other-id'; UserSid = $sp.Firewall[0].UserSid }, $sp.Firewall[1])
        & $T 'fw-identity: rule with a different id than recorded is refused and survives' { (& $Refused 'fw-identity' { Remove-AllowedFirewallRule $badId $sp.Firewall[0].DisplayName }) -and (& $exists.fw $sp.Firewall[0].Name) }
        $badUser = (Copy-Spec $sp); $badUser.Firewall = @($sp.Firewall[0], [ordered]@{ DisplayName = $sp.Firewall[1].DisplayName; Name = $sp.Firewall[1].Name; UserSid = 'S-1-5-21-9-9-9-9' })
        & $T 'fw-identity: rule scoped to a different SID is refused' { & $Refused 'fw-identity' { Remove-AllowedFirewallRule $badUser $sp.Firewall[1].DisplayName } }
        & $T 'name-allowlist: a rule on the bystander name is refused and survives' { (& $Refused 'name-allowlist' { Remove-AllowedFirewallRule $sp $fx1.Bystander }) -and (& $exists.fw $fx1.Bystander) }
        & $T 'fw-identity: toggle off removes the mismatched rule (the lock was the blocker)' { & $With @('fw-identity') { Remove-AllowedFirewallRule $badId $sp.Firewall[0].DisplayName }; -not (& $exists.fw $sp.Firewall[0].Name) }
        Set-NetFirewallRule -Name $sp.Firewall[1].Name -LocalUser "D:(A;;CC;;;$($sp.Users[0].Sid))(A;;CC;;;$($sp.Users[1].Sid))"
        & $T 'fw-identity: rule scoped to the account plus another SID is refused and survives' { (& $Refused 'fw-identity' { Remove-AllowedFirewallRule $sp $sp.Firewall[1].DisplayName }) -and (& $exists.fw $sp.Firewall[1].Name) }
        & $T 'fw-identity: toggle off removes it (the lock was the blocker)' { & $With @('fw-identity') { Remove-AllowedFirewallRule $sp $sp.Firewall[1].DisplayName }; -not (& $exists.fw $sp.Firewall[1].Name) }
        # registry
        & $T 'name-allowlist: registry value not on the list is refused and survives' { (& $Refused 'name-allowlist' { Remove-AllowedRegistryValue $sp $fx1.Keep }) -and ((Get-Item $sp.Registry.Path).GetValueNames() -contains $fx1.Keep) }
        New-ItemProperty -Path $sp.Registry.Path -Name $fx1.Ub -PropertyType String -Value 'text' -Force | Out-Null
        & $T 'reg-value-shape: value of another shape is refused' { & $Refused 'reg-value-shape' { Remove-AllowedRegistryValue $sp $fx1.Ub } }
        & $T 'reg-value-shape: toggle off removes it (the lock was the blocker)' { & $With @('reg-value-shape') { Remove-AllowedRegistryValue $sp $fx1.Ub }; (Get-Item $sp.Registry.Path).GetValueNames() -cnotcontains $fx1.Ub }
        # acl: unlisted path, link
        $unl = "$($fx1.Root)\unlisted"; New-Item -ItemType Directory $unl | Out-Null
        $acl = Get-Acl $unl; $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fx1.CapB, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl $unl $acl
        & $T 'name-allowlist: ACL path not on the list is refused and its entry stays' { (& $Refused 'name-allowlist' { Remove-SidAcesTree $sp $unl }) -and ((Get-SidAces $unl $fx1.CapB).Count -eq 1) }
        & $T 'name-allowlist: ACL toggle off purges it (the lock was the blocker)' { & $With @('name-allowlist') { $null = Remove-SidAcesTree $sp $unl }; (Get-SidAces $unl $fx1.CapB).Count -eq 0 }
        $lnkRoot = "$($fx1.Root)\linkdest"; New-Item -ItemType Directory $lnkRoot | Out-Null
        $acl = Get-Acl $lnkRoot; $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fx1.CapA, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl $lnkRoot $acl
        $lnk = "$($fx1.Root)\link"; New-Item -ItemType Junction -Path $lnk -Target $lnkRoot | Out-Null
        $lnkSpec = (Copy-Spec $sp); $lnkSpec.AclTargets = @([ordered]@{ Id = 'L'; Path = $lnk; Sid = $fx1.CapA; Scan = $false })
        & $T 'acl-reparse: a link target is refused and the destination keeps its entry' { (& $Refused 'acl-reparse' { Remove-SidAcesTree $lnkSpec $lnk }) -and ((Get-SidAces $lnkRoot $fx1.CapA).Count -eq 1) }
        & $T 'acl-reparse: toggle off, the refusal is gone (the walk then meets the link as a path that resolves elsewhere)' { $script:SimulateOnly = $true; try { $msg = try { & $With @('acl-reparse') { $null = Remove-SidAcesTree $lnkSpec $lnk }; '' } catch { $_.Exception.Message }; $msg -notlike 'REFUSED`[acl-reparse`]*' } finally { $script:SimulateOnly = $false; $script:SimLog.Clear() } }
        # destructive layer: the link is removed before folders are deleted
        [IO.Directory]::Delete($lnk)

        # ---- whole-run locks on fresh fixtures
        $bkFile = "$bk\notadir"; 'x' | Set-Content $bkFile
        $fx2 = New-Fixture 'f2'; $d2 = Invoke-DryRun $fx2.Spec (Test-Elevated)
        & $T 'dry run: fixture is fully present and clean' { ($d2.Findings.Count -eq 0) -and (@($d2.Plan | Where-Object { -not $_.present -and $_.kind -cne 'disable' }).Count -eq 0) -and ($d2.Plan.Count -eq 13) }
        & $T 'dry run: digest is stable for an unchanged state' { (Invoke-DryRun $fx2.Spec (Test-Elevated)).Digest -ceq $d2.Digest }
        $v0 = Invoke-VerifyRun $fx2.Spec (Test-Elevated) 20
        & $T 'verify: reports FAIL on the untouched fixture' { -not $v0.ok }
        $soDir = "$($fx2.Root)\scanonly"; New-Item -ItemType Directory $soDir | Out-Null
        $soAcl = Get-Acl $soDir; $soAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fx2.ExtraSid, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl $soDir $soAcl
        $spSo = (Copy-Spec $fx2.Spec); $spSo.AclTargets = @([ordered]@{ Id = 'A9'; Path = $soDir; Sid = $fx2.CapB; Scan = $true })
        & $T 'scan-only-sid: an entry this script never removes stops the run before any change' { & $Refused 'scan-only-sid' { Write-Backup $spSo $d2.State $d2.Digest $bkW -SnapSecs 60 } }
        & $T 'scan-only-sid: toggle off, the backup goes through (the lock was the blocker)' { & $With @('scan-only-sid') { $null = Write-Backup $spSo $d2.State $d2.Digest $bkW -SnapSecs 60 }; $true }
        & $T 'tree-snapshot: a snapshot cut short by the time limit refuses the backup' { & $Refused 'tree-snapshot' { Write-Backup $fx2.Spec $d2.State $d2.Digest $bkW -SnapSecs -1 } }
        & $T 'tree-snapshot: toggle off, the same call completes (the lock was the blocker)' { & $With @('tree-snapshot') { $null = Write-Backup $fx2.Spec $d2.State $d2.Digest $bkW -SnapSecs -1 }; $true }
        & $T 'tree-snapshot: a normal snapshot holds one line per object read' { $bd = Write-Backup $fx2.Spec $d2.State $d2.Digest $bkW -SnapSecs 60; $n = 0; foreach ($l in [IO.File]::ReadLines("$bd\tree-snapshot.tsv")) { $n++ }; ($n -eq $script:LastSnapshot.lines) -and ($n -gt 15) }
        $cbDir = "$($fx2.Root)\cb"; New-Item -ItemType Directory "$cbDir\deep" -Force | Out-Null
        $cbAcl = Get-Acl $cbDir; $cbAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fx2.CapA, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl $cbDir $cbAcl
        $spCb1 = (Copy-Spec $fx2.Spec); $spCb1.AclTargets = @([ordered]@{ Id = 'A7'; Path = $cbDir; Sid = $fx2.CapA; Scan = $true })
        & $T 'codex-below-root: an explicit entry only on the folder being purged is not refused (probe discriminates)' { $null = Write-Backup $spCb1 $d2.State $d2.Digest $bkW -SnapSecs 60; $true }
        $cdAcl = Get-Acl "$cbDir\deep"; $cdAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fx2.CapA, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl "$cbDir\deep" $cdAcl
        & $T 'codex-below-root: an explicit Codex entry below the purged folder stops the run before any change' { & $Refused 'codex-below-root' { Write-Backup $spCb1 $d2.State $d2.Digest $bkW -SnapSecs 60 } }
        & $T 'codex-below-root: toggle off, the same call completes (the lock was the blocker)' { & $With @('codex-below-root') { $null = Write-Backup $spCb1 $d2.State $d2.Digest $bkW -SnapSecs 60 }; $true }
        Remove-Item -LiteralPath $cbDir -Recurse -Force
        $script:ReadFault = { param($path) $path -like '*\repo\README.md' }
        & $T 'snapshot-unreadable: an object that cannot be read stops the run before any change' { & $Refused 'snapshot-unreadable' { Write-Backup $fx2.Spec $d2.State $d2.Digest $bkW -SnapSecs 60 } }
        & $T 'snapshot-unreadable: toggle off, the same call completes (the lock was the blocker)' { & $With @('snapshot-unreadable') { $null = Write-Backup $fx2.Spec $d2.State $d2.Digest $bkW -SnapSecs 60 }; $true }
        $script:ReadFault = $null
        $bdir = Write-Backup $fx2.Spec $d2.State $d2.Digest $bkW -SnapSecs 60
        & $T 'backup folder: created already protected - SYSTEM and Administrators only, owned by Administrators, not inheriting' { Assert-AdminOnlyDirectory $bdir; $ba = [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($bdir), [Security.AccessControl.AccessControlSections]'Access,Owner'); $ba.AreAccessRulesProtected -and ($script:TrustedOwners -ccontains $ba.GetOwner([Security.Principal.SecurityIdentifier]).Value) -and (@($ba.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | Where-Object { $script:TrustedOwners -cnotcontains $_.IdentityReference.Value }).Count -eq 0) }
        $openDir = "$bk\openbackup"; New-Item -ItemType Directory $openDir | Out-Null
        & $T 'backup folder: an ordinary inheriting folder is refused (probe discriminates)' { & $Refused 'backup-dir-secure' { Assert-AdminOnlyDirectory $openDir } }
        & $T 'backup folder: toggle off, the same ordinary folder is accepted (the lock was the blocker)' { & $With @('backup-dir-secure') { Assert-AdminOnlyDirectory $openDir; $true } }
        $realBk = "$bk\realroot"; New-Item -ItemType Directory $realBk | Out-Null; $linkBk = "$bk\linkroot"; New-Item -ItemType Junction -Path $linkBk -Target $realBk | Out-Null
        & $T 'backup folder: a backup root that is a link is refused before anything is written' { & $Refused 'backup-dir-secure' { Write-Backup $fx2.Spec $d2.State $d2.Digest $linkBk -SnapSecs 60 } }
        & $T 'backup folder: toggle off, the same call writes through the link (the lock was the blocker)' { & $With @('backup-dir-secure') { $null = Write-Backup $fx2.Spec $d2.State $d2.Digest $linkBk -SnapSecs 60 }; @(Get-ChildItem $realBk).Count -ge 1 }
        [IO.Directory]::Delete($linkBk)
        & $T 'export scratch: made under a protected root and removed after use' { $null = Get-HeavyState $fx2.Spec $true; Assert-AdminOnlyDirectory $script:AdminTempRoot; (Test-Path $script:AdminTempRoot) -and (@(Get-ChildItem $script:AdminTempRoot -Force).Count -eq 0) }
        $rootNew = "$($script:AdminTempRoot)\bkroot"
        & $T 'backup root: a missing root under the protected folder is created protected, and so is the backup folder in it' { $bdn = Write-Backup $fx2.Spec $d2.State $d2.Digest $rootNew -SnapSecs 60; Assert-AdminOnlyDirectory $rootNew; Assert-AdminOnlyDirectory $bdn; (Test-Path "$bdn\backup.json") }
        & $T 'restore: refused on the real spec before anything is read, and with that lock off the next independent lock (selftest-no-real) still refuses' { $m1 = try { $null = Invoke-RestoreAcl $real $bkW '' $true; '' } catch { $_.Exception.Message }; $m2 = try { & $With @('restore-real-blocked') { $null = Invoke-RestoreAcl $real $bkW '' $true }; '' } catch { $_.Exception.Message }; ($m1 -like 'REFUSED`[restore-real-blocked`]*') -and ($m2 -like 'REFUSED`[selftest-no-real`]*') }
        $cmdPath = Join-Path (Split-Path -Parent $script:SelfPath) 'remove_codex_sandbox.cmd'
        & $T 'launcher stub: with a hash that does not match it copies into a protected folder, refuses and runs nothing (skipped when the .cmd is not beside the script)' {
            if (-not (Test-Path -LiteralPath $cmdPath)) { return $true }
            $b64 = [regex]::Match([IO.File]::ReadAllText($cmdPath), "'-EncodedCommand','([A-Za-z0-9+/=]+)'").Groups[1].Value
            $pd = "$($script:ThrowRoot)\$($script:Own)pd"; New-Item -ItemType Directory $pd | Out-Null
            $srcCopy = "$pd\stubsrc.ps1"; 'Write-Host should-never-run' | Set-Content $srcCopy
            $env:ProgramData = $pd; $env:RCS_PS1 = $srcCopy; $env:RCS_SHA = ('0' * 64)
            try { $out = ("`n" | & pwsh -NoProfile -ExecutionPolicy Bypass -EncodedCommand $b64 2>&1 | Out-String); $rc = $LASTEXITCODE } finally { $env:ProgramData = $pdWas; Remove-Item Env:\RCS_PS1, Env:\RCS_SHA -ErrorAction SilentlyContinue }
            $run = "$pd\blarai-operator\run-1743"
            Assert-AdminOnlyDirectory "$pd\blarai-operator"; Assert-AdminOnlyDirectory $run
            ($rc -eq 2) -and $out.Contains('REFUSED: the script changed') -and $out.Contains('Hash of the protected copy') -and -not $out.Contains('should-never-run') -and (Test-Path "$run\remove_codex_sandbox.ps1") }
        & $T 'plan-digest: a wrong digest is refused and nothing changes' { $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan ('0' * 64) -BackupRoot $bk; ($r.code -eq 2) -and ($r.message -like 'REFUSED`[plan-digest`]*') -and (& $exists.user $fx2.Ua) -and ((Get-SidAces $fx2.Spec.AclTargets[1].Path $fx2.CapA).Count -gt 0) }
        & $T 'plan-digest: a missing digest is refused' { $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan '' -BackupRoot $bk; $r.message -like 'REFUSED`[plan-digest`]*' }
        & $T 'elevation: apply as non-admin is refused before anything else' { $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan $d2.Digest -BackupRoot $bk -IsAdmin $false; ($r.message -like 'REFUSED`[elevation`]*') -and (& $exists.user $fx2.Ua) }
        & $T 'backup-readback: unwritable backup location is refused and nothing changes' { $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan $d2.Digest -BackupRoot $bkFile; ($r.message -like 'REFUSED`[backup-readback`]*') -and (& $exists.user $fx2.Ua) -and (& $exists.group $fx2.Group) }
        $script:BackupTamper = { param($p) Add-Content -LiteralPath $p -Value 'tampered' }
        & $T 'backup-readback: a backup that reads back different is refused and nothing changes' { $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan $d2.Digest -BackupRoot $bk; ($r.message -like 'REFUSED`[backup-readback`]*') -and (& $exists.user $fx2.Ua) }
        $script:BackupTamper = $null
        # unexpected live state: an extra rule matching the glob
        New-NetFirewallRule -Name "$($script:Own)fwid-f2-extra" -DisplayName "$($script:Own)fw-f2-extra" -Direction Outbound -Action Block -Protocol TCP -RemoteAddress '127.0.0.0/8' -Enabled False | Out-Null; $script:Created.Add("fw:$($script:Own)fwid-f2-extra")
        $d2b = Invoke-DryRun $fx2.Spec (Test-Elevated)
        & $T 'unexpected-live: an extra matching rule makes apply refuse and change nothing' { $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan $d2b.Digest -BackupRoot $bk; ($r.message -like 'REFUSED`[unexpected-live`]*') -and (& $exists.user $fx2.Ua) }
        Remove-NetFirewallRule -Name "$($script:Own)fwid-f2-extra"
        # an export that did not run: the digest still matches the approved plan, and the apply must still refuse
        $fx4 = New-Fixture 'f4'; $d4 = Invoke-DryRun $fx4.Spec (Test-Elevated)
        $script:ExportFault = 'wfp-missing'
        & $T 'heavy: apply with a check that could not run is refused although the plan digest matches, and nothing changes' { $r4 = Invoke-Apply -Spec $fx4.Spec -ExpectPlan $d4.Digest -BackupRoot $bk; ($r4.code -eq 2) -and ($r4.message -like 'REFUSED`[unexpected-live`]*') -and (& $exists.user $fx4.Ua) -and (& $exists.group $fx4.Group) -and ((Get-SidAces "$($fx4.Root)\repo" $fx4.CapA).Count -gt 0) }
        & $T 'heavy: unexpected-live lock off, the same apply goes ahead (the lock was the blocker)' { & $With @('unexpected-live') { $null = Invoke-Apply -Spec $fx4.Spec -ExpectPlan $d4.Digest -BackupRoot $bk -ScanSecs 60 }; -not (& $exists.user $fx4.Ua) }
        $script:ExportFault = $null
        # the state moves after the dry run without raising any finding: the digest no longer matches
        $snapFolder = (Get-Item -LiteralPath $fx2.Spec.ReportOnly).FullName; $hashBefore = (Get-FileHash "$snapFolder\auth.json").Hash
        $ux2 = "$($script:Own)ux-2"; New-LocalUser -Name $ux2 -Password $pw -Disabled | Out-Null; $script:Created.Add("user:$ux2")
        $d2d = Invoke-DryRun $fx2.Spec (Test-Elevated)
        Set-NetFirewallRule -Name $fx2.Spec.Firewall[0].Name -Enabled True
        & $T 'plan-digest: state changed after the dry run is refused and nothing changes' { $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan $d2d.Digest -BackupRoot $bk; ($r.message -like 'REFUSED`[plan-digest`]*') -and (& $exists.user $fx2.Ua) }
        $ovmsOthers = { param($root) @((Get-AclAccess "$root\ovms").GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -cne $fx2.CapB }).Count }
        $othersBefore = & $ovmsOthers $fx2.Root
        $ownerBefore = (Get-AclTargetState $fx2.Spec.AclTargets[3]).owner
        $ovmsPre = (Get-AclAccess "$($fx2.Root)\ovms").GetSecurityDescriptorSddlForm('Access'); $parentOfOvms = (Get-AclAccess $fx2.Root).GetSecurityDescriptorSddlForm('Access')
        # happy path
        $dFinal = Invoke-DryRun $fx2.Spec (Test-Elevated)
        $r = Invoke-Apply -Spec $fx2.Spec -ExpectPlan $dFinal.Digest -BackupRoot $bk
        & $T 'apply: PASS with exit code 0' { ($r.ok) -and ($r.code -eq 0) -and ($r.verdict -eq 'PASS') }
        & $T 'apply: PASS rests on a finished scan of every object in the three trees' { $r.certified -and ($r.scans.Count -eq 3) -and (@($r.scans | Where-Object { $_.scanned -le 0 -or $_.foldersLeftUnscanned -gt 0 -or $_.unreadable -gt 0 }).Count -eq 0) -and ((($r.scans | ForEach-Object { $_.scanned } | Measure-Object -Sum).Sum) -gt 15) }
        & $T 'apply: the backup holds tree-snapshot.tsv' { Test-Path "$($r.backupDir)\tree-snapshot.tsv" }
        & $T 'scan: a name Win32 normalises away (trailing dot) is read through the extended path, not left unreadable' { $dotPath = "$($fx2.Root)\temp\mv\dot."; $plainFails = try { $null = [IO.FileSystemAclExtensions]::GetAccessControl([IO.FileInfo]$dotPath, [Security.AccessControl.AccessControlSections]::Access); $false } catch { $true }; $plainFails -and @(Get-Content "$($r.backupDir)\tree-snapshot.tsv" | Where-Object { $_ -like "$dotPath`t*" }).Count -eq 1 }
        & $T 'collateral: removal of the Codex SID alone is not listed (probe discriminates)' { @($r.collateral | Where-Object { $_ -like '*\repo\sub*' -or $_ -like '*\ovms\bin*' }).Count -eq 0 }
        & $T 'collateral: no collateral.txt when nothing changed for other principals' { -not (Test-Path "$($r.backupDir)\collateral.txt") }
        & $T 'owner: the owner of the A10 folder is unchanged by the apply' { $o2 = (Get-AclTargetState $fx2.Spec.AclTargets[3]).owner; ($o2 -ceq $ownerBefore) -and ($o2 -ceq 'S-1-5-32-544') }
        & $T 'owner: the check sees a changed owner (probe discriminates)' { $od = "$($fx2.Root)\ownerprobe"; New-Item -ItemType Directory $od | Out-Null; $ot = [ordered]@{ Id = 'O'; Path = $od; Sid = $fx2.CapB }; $b4 = (Get-AclTargetState $ot).owner; $oa = [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]$od, [Security.AccessControl.AccessControlSections]::Owner); $oa.SetOwner($(if ($b4 -ceq 'S-1-5-32-544') { [Security.Principal.WindowsIdentity]::GetCurrent().User } else { [Security.Principal.SecurityIdentifier]'S-1-5-32-544' })); [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]$od, $oa); $b4 -cne (Get-AclTargetState $ot).owner }
        & $T 'apply: backup folder holds backup.json, undo-commands.txt and report.json' { ($r.backupDir) -and (Test-Path "$($r.backupDir)\backup.json") -and (Test-Path "$($r.backupDir)\undo-commands.txt") -and (Test-Path "$($r.backupDir)\report.json") }
        & $T 'apply: accounts, group, rules, registry values are gone' { -not (& $exists.user $fx2.Ua) -and -not (& $exists.user $fx2.Ub) -and -not (& $exists.group $fx2.Group) -and -not (& $exists.fw $fx2.Spec.Firewall[0].Name) -and -not (& $exists.fw $fx2.Spec.Firewall[1].Name) -and ((Get-Item $fx2.Spec.Registry.Path).GetValueNames() -cnotcontains $fx2.Ua) }
        & $T 'apply: the bystander rule, the other registry value and the foreign user survive' { (& $exists.fw $fx2.Bystander) -and ((Get-Item $fx2.Spec.Registry.Path).GetValueNames() -contains $fx2.Keep) -and (& $exists.user $ux2) }
        $sc = Find-SidAcesDeep $fx2.Root @($fx2.CapA, $fx2.CapB) 60
        & $T 'apply: no object under the fixture carries either capability SID (deep scan)' { ($sc.hits -eq 0) -and ($sc.scanned -gt 15) }
        & $T 'apply: no folder was set to stop inheriting, and the A10 folder kept every other entry' { (-not (Get-AclAccess "$($fx2.Root)\ovms").AreAccessRulesProtected) -and ($othersBefore -ge 1) -and ((& $ovmsOthers $fx2.Root) -eq $othersBefore) }
        & $T 'apply: the left-alone folder is byte-identical' { (Get-FileHash "$snapFolder\auth.json").Hash -ceq $hashBefore }
        $v1 = Invoke-VerifyRun $fx2.Spec (Test-Elevated) 60
        & $T 'verify: PASS after apply' { $v1.ok }
        $vCut = Invoke-VerifyRun $fx2.Spec (Test-Elevated) -1
        & $T 'verify: a scan cut short by the time limit is not a PASS' { (-not $vCut.ok) -and (@($vCut.problems | Where-Object { $_ -like '*cannot certify*' }).Count -ge 1) }
        & $T 'verify: complete-scan lock off (mutation), the same cut scan reads as PASS' { & $With @('scan-complete') { (Invoke-VerifyRun $fx2.Spec (Test-Elevated) -1).ok } }
        & $T 'apply: a second run changes nothing and passes' { $dr = Invoke-DryRun $fx2.Spec (Test-Elevated); $r2 = Invoke-Apply -Spec $fx2.Spec -ExpectPlan $dr.Digest -BackupRoot $bk; $r2.ok -and (@($r2.steps | Where-Object { $_.result -ne 'already gone' }).Count -eq 0) }
        & $T 'undo text: restores a firewall rule and a registry value, and points at -RestoreAcl for the access lists' { $t = Get-Content "$($r.backupDir)\undo-commands.txt" -Raw; $t.Contains('New-NetFirewallRule') -and $t.Contains('New-ItemProperty') -and $t.Contains('-RestoreAcl') -and $t.Contains('exactly') }
        $undoLines = @((Get-Content "$($r.backupDir)\undo-commands.txt") | Where-Object { $_ -like 'New-NetFirewallRule*' })
        & $T 'undo text: the TCP rule keeps its remote port and the UDP rule (none) gets none' { $tcp = @($undoLines | Where-Object { $_ -like '*fwid-f2-tcp*' }); $udp = @($undoLines | Where-Object { $_ -like '*fwid-f2-udp*' }); ($tcp.Count -eq 1) -and ($udp.Count -eq 1) -and $tcp[0].Contains("-RemotePort '1-65535'") -and -not $udp[0].Contains('RemotePort') }
        & $T 'undo text: warns the restored rule points at a deleted account and names the tree snapshot' { $t = Get-Content "$($r.backupDir)\undo-commands.txt" -Raw; $t.Contains('no longer resolves') -and $t.Contains('tree-snapshot.tsv') }
        $plantDir = "$($fx2.Root)\repo\sub"; $plAcl = Get-Acl $plantDir; $plAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fx2.ExtraSid, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl $plantDir $plAcl
        $vPl = Invoke-VerifyRun $fx2.Spec (Test-Elevated) 60
        & $T 'verify: an entry for the other Codex capability SID in a scanned tree is a FAIL' { (-not $vPl.ok) -and (@($vPl.problems | Where-Object { $_ -like '*still carry a Codex SID*' }).Count -ge 1) }
        & $T 'verify: all-SIDs lock off (mutation), the same planted entry goes unseen' { & $With @('scan-all-sids') { (Invoke-VerifyRun $fx2.Spec (Test-Elevated) 60).ok } }
        # an apply whose final scan is cut short must not read PASS
        $fx5 = New-Fixture 'f5'; $d5 = Invoke-DryRun $fx5.Spec (Test-Elevated)
        $r5 = Invoke-Apply -Spec $fx5.Spec -ExpectPlan $d5.Digest -BackupRoot $bk -ScanSecs -1
        & $T 'certification: an apply whose final scan was cut short is FAIL exit 1 BEFORE the irreversible steps, not PASS' { ($r5.code -eq 1) -and ($r5.verdict -eq 'FAIL') -and $r5.stoppedBeforeIrreversible -and ($r5.message -like '*cannot certify*') -and (& $exists.user $fx5.Ua) -and (& $exists.group $fx5.Group) -and ((Get-SidAces "$($fx5.Root)\repo" $fx5.CapA).Count -eq 0) }
& $T 'certification: the same apply run again, resuming the stopped one with a workable limit, completes' { $d5b = Invoke-DryRun $fx5.Spec (Test-Elevated); $r5b = Invoke-Apply -Spec $fx5.Spec -ExpectPlan $d5b.Digest -BackupRoot $bk -ResumeFrom $r5.backupDir; ($r5b.code -eq 0) -and ($r5b.verdict -eq 'PASS') -and -not (& $exists.user $fx5.Ua) }
        & $T 'certification: report.json carries the same verdict' { (Get-Content "$($r5.backupDir)\report.json" -Raw | ConvertFrom-Json).verdict -ceq 'FAIL' }
        # ---- Stage 2 (access entries): each object's own list is edited through one handle; nothing is re-derived
        Initialize-OpNative
        $readNow = { param($p) $ext = '\\?\' + $p; $acl = if ([IO.Directory]::Exists($ext)) { [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($ext), [Security.AccessControl.AccessControlSections]::Access) } else { [IO.FileSystemAclExtensions]::GetAccessControl([IO.FileInfo]::new($ext), [Security.AccessControl.AccessControlSections]::Access) }; $acl.GetSecurityDescriptorSddlForm('Access') }
        $beforeMap = $script:LastSnapshot.before; $purgeAll = Get-PurgeSids $fx2.Spec
        & $T 'surgical: every recorded object now holds exactly its before-change list minus the Codex entries (order, inherited flags and protection included)' { $bad = 0; $n = 0; foreach ($k in @($beforeMap.Keys)) { $n++; if ((& $readNow $k) -cne (Remove-SidsFromSddl $beforeMap[$k] $purgeAll)) { $bad++ } }; ($bad -eq 0) -and ($n -gt 15) }
        & $T 'surgical: the stale inherited entries on the Temp-shaped root are still there, still inherited - nothing was re-derived' { (@(Get-SidAces "$($fx2.Root)\temp" $fx2.StaleSid | Where-Object { $_ -like '*inherited' }).Count -ge 2) }
        & $T 'surgical: the moved-in folder did not catch up with what its parent hands down (no gain for the unrelated principal)' { (Get-SidAces "$($fx2.Root)\temp\mv" $fx2.StaleSid).Count -eq 0 }
        & $T 'surgical: the ovms-shaped folder did not re-inherit from its parent (the parent hands down an entry the folder never had)' { ($parentOfOvms -match ';;;AU\)') -and ($ovmsPre -notmatch ';;;AU\)') -and (((& $readNow "$($fx2.Root)\ovms") -notmatch ';;;AU\)')) -and (((& $readNow "$($fx2.Root)\ovms\bin\a.dll") -notmatch ';;;AU\)')) }
        & $T 'surgical: no folder was set to stop inheriting, and no protected one was changed in protection' { (-not (Get-AclAccess "$($fx2.Root)\ovms").AreAccessRulesProtected) -and ((Get-AclAccess "$($fx2.Root)\temp").AreAccessRulesProtected -eq $false) }
        & $T 'read-back: an unchanged object other than the Codex entries is compared by the cheap string check' { (($r.scans | ForEach-Object { $_.fastCompared } | Measure-Object -Sum).Sum -gt 0) -and (($r.scans | ForEach-Object { $_.slowCompared } | Measure-Object -Sum).Sum -eq 0) }
        & $T 'snapshot memory: identical lists share one string instance' { $a1 = Get-Interned ('D:AI(A;ID;FA;;;SY)' + 'x'); $a2 = Get-Interned ('D:AI(A;ID;FA;;;SY)' + 'x'); [object]::ReferenceEquals($a1, $a2) }
        # the walk checks each object on its own handle
        $fxj = New-Fixture 'j1'; $dj = Invoke-DryRun $fxj.Spec (Test-Elevated)
        New-Item -ItemType Directory "$($fxj.Root)\repo\par", "$($fxj.Root)\victim" -Force | Out-Null; 'x' | Set-Content "$($fxj.Root)\repo\par\f2.txt"; 'v' | Set-Content "$($fxj.Root)\victim\f2.txt"
        $vAcl = Get-Acl "$($fxj.Root)\victim\f2.txt"; $vAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fxj.CapA, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl "$($fxj.Root)\victim\f2.txt" $vAcl
        $dj = Invoke-DryRun $fxj.Spec (Test-Elevated)
        $swap = { param($path) if ($path -like '*\repo\par\f2.txt') { Rename-Item "$($fxj.Root)\repo\par" 'par_real'; New-Item -ItemType Junction -Path "$($fxj.Root)\repo\par" -Target "$($fxj.Root)\victim" | Out-Null } }
        $script:WalkHook = $swap
        $rj = Invoke-Apply -Spec $fxj.Spec -ExpectPlan $dj.Digest -BackupRoot $bk
        $script:WalkHook = $null
        & $T 'acl-handle: a folder swapped for a link after the snapshot is refused, and the object outside the tree is untouched' { ($rj.code -eq 3) -and ($rj.message -like '*resolves to*') -and ((Get-SidAces "$($fxj.Root)\victim\f2.txt" $fxj.CapA).Count -eq 1) -and (& $exists.user $fxj.Ua) }
        $fxj2 = New-Fixture 'j2'
        New-Item -ItemType Directory "$($fxj2.Root)\repo\par", "$($fxj2.Root)\victim" -Force | Out-Null; 'x' | Set-Content "$($fxj2.Root)\repo\par\f2.txt"; 'v' | Set-Content "$($fxj2.Root)\victim\f2.txt"
        $vAcl2 = Get-Acl "$($fxj2.Root)\victim\f2.txt"; $vAcl2.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$fxj2.CapA, [Security.AccessControl.FileSystemRights]0x1201bf, 'Allow')); Set-Acl "$($fxj2.Root)\victim\f2.txt" $vAcl2
        $dj2 = Invoke-DryRun $fxj2.Spec (Test-Elevated)
        $script:WalkHook = { param($path) if ($path -like '*\repo\par\f2.txt') { Rename-Item "$($fxj2.Root)\repo\par" 'par_real'; New-Item -ItemType Junction -Path "$($fxj2.Root)\repo\par" -Target "$($fxj2.Root)\victim" | Out-Null } }
        $rj2 = & $With @('acl-handle') { Invoke-Apply -Spec $fxj2.Spec -ExpectPlan $dj2.Digest -BackupRoot $bk }
        $script:WalkHook = $null
        & $T 'acl-handle: toggle off, the same swap lets the write reach the object outside the tree (the lock was the blocker)' { (Get-SidAces "$($fxj2.Root)\victim\f2.txt" $fxj2.CapA).Count -eq 0 }
        $fxh = New-Fixture 'h1'
        'x' | Set-Content "$($fxh.Root)\repo\orig.txt"; New-Item -ItemType Directory "$($fxh.Root)\victim" | Out-Null; New-Item -ItemType HardLink -Path "$($fxh.Root)\victim\hl.txt" -Target "$($fxh.Root)\repo\orig.txt" | Out-Null
        $dh = Invoke-DryRun $fxh.Spec (Test-Elevated)
        $rh = Invoke-Apply -Spec $fxh.Spec -ExpectPlan $dh.Digest -BackupRoot $bk
        & $T 'acl-handle: a file with a second name (hard link) is refused and its shared list is untouched' { ($rh.code -eq 3) -and ($rh.message -like '*hard link*') -and ((Get-SidAces "$($fxh.Root)\victim\hl.txt" $fxh.CapA).Count -eq 1) -and (& $exists.user $fxh.Ua) }
        $fxh2 = New-Fixture 'h2'
        'x' | Set-Content "$($fxh2.Root)\repo\orig.txt"; New-Item -ItemType Directory "$($fxh2.Root)\victim" | Out-Null; New-Item -ItemType HardLink -Path "$($fxh2.Root)\victim\hl.txt" -Target "$($fxh2.Root)\repo\orig.txt" | Out-Null
        $dh2 = Invoke-DryRun $fxh2.Spec (Test-Elevated)
        $null = & $With @('acl-handle') { Invoke-Apply -Spec $fxh2.Spec -ExpectPlan $dh2.Digest -BackupRoot $bk }
        & $T 'acl-handle: toggle off, the hard link''s shared list is changed from the other name too (the lock was the blocker)' { (Get-SidAces "$($fxh2.Root)\victim\hl.txt" $fxh2.CapA).Count -eq 0 }
        # LA decision 2026-10-11: other names of a hard-linked file may live under a pinned LinkRoots folder (its subtree only)
        $fxl = New-Fixture 'l1'
        'x' | Set-Content "$($fxl.Root)\repo\orig.txt"; 'y' | Set-Content "$($fxl.Root)\repo\orig2.txt"; 'z' | Set-Content "$($fxl.Root)\repo\orig3.txt"
        New-Item -ItemType Directory "$($fxl.Root)\linkroot\sub", "$($fxl.Root)\linkroot-x" | Out-Null
        New-Item -ItemType HardLink -Path "$($fxl.Root)\linkroot\sub\hl.txt" -Target "$($fxl.Root)\repo\orig.txt" | Out-Null
        New-Item -ItemType HardLink -Path "$($fxl.Root)\linkroot-x\hl2.txt" -Target "$($fxl.Root)\repo\orig2.txt" | Out-Null
        $spL = (Copy-Spec $fxl.Spec); $spL.LinkRoots = @("$($fxl.Root)\linkroot")
        & $T 'link roots: a name inside the approved link folder is allowed, so the shared list is edited once and both names agree' { $rl = Remove-ObjectSids "$($fxl.Root)\repo\orig.txt" @($fxl.CapA) (Get-LinkNameRoots $spL); ($rl -ceq 'changed') -and ((& $readNow "$($fxl.Root)\repo\orig.txt") -ceq (& $readNow "$($fxl.Root)\linkroot\sub\hl.txt")) -and -not (& $readNow "$($fxl.Root)\linkroot\sub\hl.txt").Contains($fxl.CapA) }
        & $T 'link roots: a look-alike sibling folder is not inside it and is refused, and the list stays' { $rl2 = Remove-ObjectSids "$($fxl.Root)\repo\orig2.txt" @($fxl.CapA) (Get-LinkNameRoots $spL); ($rl2 -like 'refused*outside*') -and (& $readNow "$($fxl.Root)\linkroot-x\hl2.txt").Contains($fxl.CapA) }
        'w' | Set-Content "$($fxl.Root)\repo\orig4.txt"; New-Item -ItemType HardLink -Path "$($fxl.Root)\linkroot\sub\hl3.txt" -Target "$($fxl.Root)\repo\orig3.txt" | Out-Null; New-Item -ItemType HardLink -Path "$($fxl.Root)\linkroot\sub\hl4.txt" -Target "$($fxl.Root)\repo\orig4.txt" | Out-Null
        & $T 'link roots: with no approved folder the same name is refused (the setting is what allows it)' { $rl3 = Remove-ObjectSids "$($fxl.Root)\repo\orig3.txt" @($fxl.CapA) (Get-LinkNameRoots $fxl.Spec); ($rl3 -like 'refused*outside*') -and (& $readNow "$($fxl.Root)\linkroot\sub\hl3.txt").Contains($fxl.CapA) }
        & $T 'link roots: toggle off, the approved folder is not honoured and the same name is refused (the lock was the blocker)' { $rl4 = & $With @('link-roots') { Remove-ObjectSids "$($fxl.Root)\repo\orig4.txt" @($fxl.CapA) (Get-LinkNameRoots $spL) }; ($rl4 -like 'refused*outside*') -and (& $readNow "$($fxl.Root)\linkroot\sub\hl4.txt").Contains($fxl.CapA) }
        & $T 'link roots: the real spec pins exactly the one approved folder' { ($real.LinkRoots.Count -eq 1) -and ($real.LinkRoots[0] -ceq 'C:\Users\mrbla\blarai-wt-1616-accuracy\models') }
        # a list that holds only Codex entries would be left empty
        $fxe = New-Fixture 'e1'
        $onlyDir = "$($fxe.Root)\repo\onlyd"; New-Item -ItemType Directory $onlyDir | Out-Null; $onlyFile = "$onlyDir\only.txt"; 'x' | Set-Content $onlyFile
        $heo = [OpAcl]::Open($onlyFile); try { [OpAcl]::SetSddl($heo, (ConvertTo-WritableSddl "D:AI(A;ID;FA;;;$($fxe.CapA))")) } finally { $heo.Dispose() }
        $de = Invoke-DryRun $fxe.Spec (Test-Elevated)
        & $T 'empty-after: a list holding only Codex entries stops the run at the snapshot, before any change' { & $Refused 'empty-after' { Write-Backup $fxe.Spec $de.State $de.Digest $bkW -SnapSecs 60 } }
        & $T 'empty-after: toggle off, the snapshot goes through (the lock was the blocker)' { & $With @('empty-after') { $null = Write-Backup $fxe.Spec $de.State $de.Digest $bkW -SnapSecs 60 }; $true }
        $spEo = (Copy-Spec $fxe.Spec); $spEo.AclTargets = @([ordered]@{ Id = 'A7'; Path = $onlyDir; Sid = $fxe.CapA; Scan = $true })
        & $T 'empty-after: the walk itself also refuses that object, with the list left as it was' { $m = try { $null = Remove-SidAcesTree $spEo $onlyDir; '' } catch { $_.Exception.Message }; ($m -like '*empty access list*') -and ((Get-SidAces $onlyFile $fxe.CapA).Count -eq 1) }
        & $T 'empty-after: toggle off (simulated), the walk would write the empty list' { $script:SimulateOnly = $true; $script:SimLog.Clear(); try { & $With @('empty-after') { $null = Remove-SidAcesTree $spEo $onlyDir }; $script:SimLog.Count -eq 1 } finally { $script:SimulateOnly = $false; $script:SimLog.Clear() } }
        $heo = [OpAcl]::Open($onlyFile); try { [OpAcl]::SetSddl($heo, (ConvertTo-WritableSddl 'D:AI(A;;FA;;;BA)')) } finally { $heo.Dispose() }
        # out-of-band changes between the removal and the read-back
        $fx6 = New-Fixture 'f6'; $d6 = Invoke-DryRun $fx6.Spec (Test-Elevated)
        $script:AfterRemovalHook = { $hh = [OpAcl]::Open("$($fx6.Root)\temp\mv\f.txt"); try { [OpAcl]::SetSddl($hh, (ConvertTo-WritableSddl (Remove-SidsFromSddl ([OpAcl]::GetSddl($hh)) @($fx6.OtherSid)))) } finally { $hh.Dispose() } }
        $r6 = Invoke-Apply -Spec $fx6.Spec -ExpectPlan $d6.Digest -BackupRoot $bk
        $script:AfterRemovalHook = $null
        & $T 'read-back: an entry lost by another principal after the removal stops the apply before the irreversible steps' { ($r6.code -eq 1) -and $r6.stoppedBeforeIrreversible -and ($r6.collateral.Count -ge 1) -and (@($r6.collateral | Where-Object { $_ -like '*\temp\mv\f.txt*' -and $_ -like "*$($fx6.OtherSid)*" }).Count -ge 1) -and ($r6.message -like '*NOT touched*') -and (& $exists.user $fx6.Ua) -and (& $exists.group $fx6.Group) -and (& $exists.fw $fx6.Spec.Firewall[0].Name) }
        & $T 'read-back: report.json says FAIL and counts the objects' { $rep6 = Get-Content "$($r6.backupDir)\report.json" -Raw | ConvertFrom-Json; ($rep6.verdict -ceq 'FAIL') -and ($rep6.collateralCount -ge 1) -and (Test-Path "$($r6.backupDir)\collateral.txt") }
        & $T 'resume: without -ResumeFrom the same apply is refused because the earlier one did not finish' { $d6b = Invoke-DryRun $fx6.Spec (Test-Elevated); $r6b = Invoke-Apply -Spec $fx6.Spec -ExpectPlan $d6b.Digest -BackupRoot $bk; ($r6b.message -like 'REFUSED`[resume-required`]*') -and (& $exists.user $fx6.Ua) }
        & $T 'resume: with -ResumeFrom the earlier snapshot is the baseline, so the earlier loss is still seen and still stops the run' { $d6c = Invoke-DryRun $fx6.Spec (Test-Elevated); $r6c = Invoke-Apply -Spec $fx6.Spec -ExpectPlan $d6c.Digest -BackupRoot $bk -ResumeFrom $r6.backupDir; ($r6c.code -eq 1) -and ($r6c.collateral.Count -ge 1) -and ($r6c.resumedFrom -ceq $r6.backupDir) -and (& $exists.user $fx6.Ua) }
        & $T 'resume: toggle off, a fresh snapshot forgets the earlier loss and the run PASSES - the blind spot the lock closes' { $d6d = Invoke-DryRun $fx6.Spec (Test-Elevated); $r6d = & $With @('resume-required') { Invoke-Apply -Spec $fx6.Spec -ExpectPlan $d6d.Digest -BackupRoot $bk }; ($r6d.code -eq 0) -and ($r6d.collateral.Count -eq 0) -and -not (& $exists.user $fx6.Ua) }
        $fx7 = New-Fixture 'f7'; $d7 = Invoke-DryRun $fx7.Spec (Test-Elevated)
        $script:AfterRemovalHook = { $hh = [OpAcl]::Open("$($fx7.Root)\temp\mv\f.txt"); try { $sd = [OpAcl]::GetSddl($hh); [OpAcl]::SetSddl($hh, (ConvertTo-WritableSddl $sd.Insert($sd.IndexOf('('), '(A;;FA;;;WD)'))) } finally { $hh.Dispose() } }
        $r7 = Invoke-Apply -Spec $fx7.Spec -ExpectPlan $d7.Digest -BackupRoot $bk
        $script:AfterRemovalHook = $null
        & $T 'read-back: an entry GAINED by another principal after the removal stops the apply just like a loss' { ($r7.code -eq 1) -and $r7.stoppedBeforeIrreversible -and (@($r7.collateral | Where-Object { $_ -like '*gained=*' }).Count -ge 1) -and (& $exists.user $fx7.Ua) }
        $fx7b = New-Fixture 'f7b'; $d7b = Invoke-DryRun $fx7b.Spec (Test-Elevated)
        $script:AfterRemovalHook = { $hh = [OpAcl]::Open("$($fx7b.Root)\temp\mv\f.txt"); try { $sd = [OpAcl]::GetSddl($hh); [OpAcl]::SetSddl($hh, (ConvertTo-WritableSddl $sd.Insert($sd.IndexOf('('), '(A;;FA;;;WD)'))) } finally { $hh.Dispose() } }
        $r7b = & $With @('collateral-stop') { Invoke-Apply -Spec $fx7b.Spec -ExpectPlan $d7b.Digest -BackupRoot $bk }
        $script:AfterRemovalHook = $null
        & $T 'read-back: toggle off (collateral-stop), the same gain goes through to a PASS (the lock was the blocker)' { ($r7b.code -eq 0) -and ($r7b.collateral.Count -ge 1) -and -not (& $exists.user $fx7b.Ua) }
        # killed at the Temp step: earlier access steps are done, a re-run must resume
        $fxs = New-Fixture 's1'; $ds = Invoke-DryRun $fxs.Spec (Test-Elevated)
        $script:StepFault = { param($st) if ($st.id -eq 'A9') { throw 'killed here' } }
        $rs = Invoke-Apply -Spec $fxs.Spec -ExpectPlan $ds.Digest -BackupRoot $bk
        $script:StepFault = $null
        & $T 'resume: an apply killed at the Temp step leaves the earlier access steps done and the rest untouched' { ($rs.code -eq 3) -and ((Get-SidAces "$($fxs.Root)\repo" $fxs.CapA).Count -eq 0) -and ((Get-SidAces "$($fxs.Root)\temp" $fxs.CapB).Count -gt 0) -and (& $exists.user $fxs.Ua) }
        $dsb = Invoke-DryRun $fxs.Spec (Test-Elevated)
        & $T 'resume: re-running it without -ResumeFrom is refused' { $rsb = Invoke-Apply -Spec $fxs.Spec -ExpectPlan $dsb.Digest -BackupRoot $bk; $rsb.message -like 'REFUSED`[resume-required`]*' }
        & $T 'resume: a folder that is not an unfinished run of this spec is refused as the target' { $rsc = Invoke-Apply -Spec $fxs.Spec -ExpectPlan $dsb.Digest -BackupRoot $bk -ResumeFrom $bkW; $rsc.message -like 'REFUSED`[resume-target`]*' }
        $rsd = Invoke-Apply -Spec $fxs.Spec -ExpectPlan $dsb.Digest -BackupRoot $bk -ResumeFrom $rs.backupDir
        & $T 'resume: with -ResumeFrom the run completes and the earlier run is marked resolved' { ($rsd.code -eq 0) -and $rsd.ok -and (Test-Path "$($rs.backupDir)\resolved.txt") -and -not (& $exists.user $fxs.Ua) }
        & $T 'resume: afterwards a plain run needs no -ResumeFrom' { $dse = Invoke-DryRun $fxs.Spec (Test-Elevated); $rse = Invoke-Apply -Spec $fxs.Spec -ExpectPlan $dse.Digest -BackupRoot $bk; $rse.ok }
        $fxs2 = New-Fixture 's2'; $ds2 = Invoke-DryRun $fxs2.Spec (Test-Elevated)
        $script:StepFault = { param($st) if ($st.id -eq 'A9') { throw 'killed here' } }
        $rs2 = Invoke-Apply -Spec $fxs2.Spec -ExpectPlan $ds2.Digest -BackupRoot $bk
        $script:StepFault = $null
        Add-Content -LiteralPath "$($rs2.backupDir)\tree-snapshot.tsv" -Value "C:\somewhere`tD:(A;;FA;;;WD)"
        $ds2b = Invoke-DryRun $fxs2.Spec (Test-Elevated)
        & $T 'resume: a baseline snapshot altered after it was written is refused (hash check)' { $rs2b = Invoke-Apply -Spec $fxs2.Spec -ExpectPlan $ds2b.Digest -BackupRoot $bk -ResumeFrom $rs2.backupDir; $rs2b.message -like 'REFUSED`[resume-baseline`]*' }
        & $T 'resume: toggle off, the altered baseline is accepted (the lock was the blocker)' { $rs2c = & $With @('resume-baseline') { Invoke-Apply -Spec $fxs2.Spec -ExpectPlan $ds2b.Digest -BackupRoot $bk -ResumeFrom $rs2.backupDir }; $rs2c.message -notlike 'REFUSED`[resume-baseline`]*' }
        # restore: exact, from a protected and hash-checked backup, only inside the allowlisted folders
        $fxr = New-Fixture 'r1'; $dr = Invoke-DryRun $fxr.Spec (Test-Elevated)
        $rr = Invoke-Apply -Spec $fxr.Spec -ExpectPlan $dr.Digest -BackupRoot $bk
        $beforeR = $script:LastSnapshot.before; $purgeR = Get-PurgeSids $fxr.Spec
        $oneR = "$($fxr.Root)\repo\sub\deep\f.txt"; $otherR = "$($fxr.Root)\repo\README.md"
        $restOne = Invoke-RestoreAcl $fxr.Spec $rr.backupDir $oneR $true
        & $T 'restore: one object is put back exactly and nothing else is touched' { ($restOne.restored -eq 1) -and ((& $readNow $oneR) -ceq $beforeR[$oneR]) -and ((& $readNow $otherR) -ceq (Remove-SidsFromSddl $beforeR[$otherR] $purgeR)) }
        $restAll = Invoke-RestoreAcl $fxr.Spec $rr.backupDir '' $true
        & $T 'restore: every recorded object comes back exactly, stale and inherited entries included' { $bad = 0; foreach ($k in @($beforeR.Keys)) { if ((& $readNow $k) -cne $beforeR[$k]) { $bad++ } }; ($bad -eq 0) -and ($restAll.problems.Count -eq 0) -and ($restAll.restored -gt 5) }
        $copyBk = "$bkW\notprotected"; New-Item -ItemType Directory $copyBk | Out-Null; Copy-Item "$($rr.backupDir)\tree-snapshot.tsv*" $copyBk
        & $T 'restore: a backup folder that is not protected is refused' { & $Refused 'backup-dir-secure' { Invoke-RestoreAcl $fxr.Spec $copyBk '' $true } }
        Add-Content -LiteralPath "$($rr.backupDir)\tree-snapshot.tsv" -Value "$otherR`tD:P(A;;FA;;;WD)"
        & $T 'restore: a snapshot altered after it was written is refused (hash check)' { & $Refused 'restore-baseline' { Invoke-RestoreAcl $fxr.Spec $rr.backupDir '' $true } }
        & $T 'restore: toggle off, the forged list would be written (simulated) - the lock was the blocker' { $script:SimulateOnly = $true; $script:SimLog.Clear(); try { & $With @('restore-baseline') { $null = Invoke-RestoreAcl $fxr.Spec $rr.backupDir $otherR $true }; $script:SimLog.Count -ge 1 } finally { $script:SimulateOnly = $false; $script:SimLog.Clear() } }
        $outDir = "$bkW\outside-$([guid]::NewGuid().ToString('N').Substring(0, 4))"; New-AdminOnlyDirectory $outDir
        [IO.File]::WriteAllText("$outDir\tree-snapshot.tsv", "$($fxr.Root)\victim-outside`tD:AI(A;;FA;;;WD)`n")
        [IO.File]::WriteAllText("$outDir\tree-snapshot.tsv.meta.json", ([ordered]@{ sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath "$outDir\tree-snapshot.tsv").Hash } | ConvertTo-Json))
        & $T 'restore: a recorded path outside the allowlisted folders is refused (even with a matching hash)' { & $Refused 'restore-path' { Invoke-RestoreAcl $fxr.Spec $outDir '' $true } }
        & $T 'restore: toggle off, the call goes on to try that outside path (the lock was the blocker)' { $rto = & $With @('restore-path') { Invoke-RestoreAcl $fxr.Spec $outDir '' $true }; $rto.problems.Count -ge 1 }
        # pure helpers of the new design
        $sdB = 'D:PAI(A;OICI;FA;;;SY)(A;OICIID;0x1201bf;;;S-1-5-21-1-2-3-4001)(A;;FR;;;S-1-5-21-1-2-3-4002)'
        & $T 'sddl: removing SIDs cuts exactly their entries and keeps the rest in order' { (Remove-SidsFromSddl $sdB @('S-1-5-21-1-2-3-4001')) -ceq 'D:PAI(A;OICI;FA;;;SY)(A;;FR;;;S-1-5-21-1-2-3-4002)' }
        & $T 'sddl: removing no SID changes nothing' { (Remove-SidsFromSddl $sdB @()) -ceq $sdB }
        & $T 'sddl: a list left without entries is recognised as empty' { (-not (Test-SddlHasAces 'D:AI')) -and (Test-SddlHasAces $sdB) }
        & $T 'sddl: the write form adds the request flag the kernel needs to keep auto-inherited, once' { ((ConvertTo-WritableSddl 'D:PAI(A;;FA;;;SY)') -ceq 'D:PARAI(A;;FA;;;SY)') -and ((ConvertTo-WritableSddl 'D:PARAI(A;;FA;;;SY)') -ceq 'D:PARAI(A;;FA;;;SY)') -and ((ConvertTo-WritableSddl 'D:(A;;FA;;;SY)') -ceq 'D:(A;;FA;;;SY)') }
        $scopeSpec = [ordered]@{ AclTargets = @([ordered]@{ Path = 'C:\a'; Sid = 'S1' }, [ordered]@{ Path = 'C:\a\.git'; Sid = 'S2' }, [ordered]@{ Path = 'C:\b'; Sid = 'S3' }) }
        & $T 'scope: an object gets the SIDs of the allowlisted folders at or above it, and a look-alike folder name gets none' { ((Get-ScopeSids $scopeSpec 'C:\a\x') -join ',') -ceq 'S1' -and ((Get-ScopeSids $scopeSpec 'C:\a\.git\y') -join ',') -ceq 'S1,S2' -and ((Get-ScopeSids $scopeSpec 'C:\ab\x').Count -eq 0) -and ((Get-ScopeSids $scopeSpec 'C:\b') -join ',') -ceq 'S3' }
        # ---- Stage 1 (Accounts): complete on its own; reads and changes no access list, takes no snapshot
        $fx8 = New-Fixture 'f8'
        $laU = "$($script:Own)ua-f8x"; $laG = "$($script:Own)grp-f8x"; $laR = "$($script:Own)xfw-f8-tcp"
        New-LocalUser -Name $laU -Password $pw -Disabled | Out-Null; $script:Created.Add("user:$laU")
        New-LocalGroup -Name $laG -Description 'look-alike group' | Out-Null; $script:Created.Add("group:$laG")
        New-NetFirewallRule -Name $laR -DisplayName $laR -Direction Outbound -Action Block -Protocol TCP -RemoteAddress '127.0.0.0/8' -Enabled False | Out-Null; $script:Created.Add("fw:$laR")
        New-Item -Path "$($fx8.RegRoot)\OtherKey" -Force | Out-Null
        New-ItemProperty -Path "$($fx8.RegRoot)\OtherKey" -Name $fx8.Ua -PropertyType DWord -Value 0 | Out-Null
        New-ItemProperty -Path "$($fx8.RegRoot)\UserList" -Name $laU -PropertyType DWord -Value 0 | Out-Null
        $aclSddl8 = (@($fx8.Spec.AclTargets | ForEach-Object { (Get-AclAccess $_.Path).GetSecurityDescriptorSddlForm('Access') })) -join "`n"
        $d8 = Invoke-DryRun $fx8.Spec (Test-Elevated) 'Accounts'
        $d8all = Invoke-DryRun $fx8.Spec (Test-Elevated) 'All'
        & $T 'stage 1: the plan holds exactly the 2 disable, 2 rule, 2 value, 2 account and 1 group steps and no access-entry step' { ($d8.Plan.Count -eq 9) -and (@($d8.Plan | Where-Object { $_.kind -ceq 'acl' }).Count -eq 0) -and ($d8all.Plan.Count -eq 13) }
        & $T 'stage 1: its plan digest differs from the full plan digest' { $d8.Digest -cne $d8all.Digest }
        & $T 'stage: any letter case selects the same plan and digest as the canonical spelling' { (Invoke-DryRun $fx8.Spec (Test-Elevated) 'accounts').Digest -ceq $d8.Digest }
        & $T 'stage: lower-case aclentries and ALL on the real spec still hit the Stage 2 refusal' { $ra = Invoke-Apply -Spec $real -ExpectPlan 'x' -BackupRoot $bk -IsAdmin $true -Stage 'aclentries'; $rb = Invoke-Apply -Spec $real -ExpectPlan 'x' -BackupRoot $bk -IsAdmin $true -Stage 'ALL'; ($ra.message -like 'REFUSED`[acl-stage-blocked`]*') -and ($rb.message -like 'REFUSED`[acl-stage-blocked`]*') }
        & $T 'stage: an unknown spelling is refused before anything changes, never an empty PASS' { $ru = Invoke-Apply -Spec $fx8.Spec -ExpectPlan $d8.Digest -BackupRoot $bk -Stage 'accountz'; ($ru.code -eq 2) -and ($ru.message -like '*unknown stage*') -and (& $exists.user $fx8.Ua) -and (& $exists.group $fx8.Group) }
        & $T 'stage: Test-StageHas rejects an unknown stage and an unknown part' { $m1 = try { $null = Test-StageHas 'bogus' 'Acl'; '' } catch { $_.Exception.Message }; $m2 = try { $null = Test-StageHas 'all' 'Nope'; '' } catch { $_.Exception.Message }; ($m1 -like '*unknown stage*') -and ($m2 -like '*unknown stage part*') -and (Test-StageHas 'ALL' 'Acl') -and (Test-StageHas 'accounts' 'Accounts') -and -not (Test-StageHas 'accounts' 'Acl') }
        $spEmpty = (Copy-Spec $fx8.Spec); $spEmpty.AclTargets = @()
        $dEmpty = Invoke-DryRun $spEmpty (Test-Elevated) 'AclEntries'
        & $T 'empty-plan: a plan with no steps is refused for an apply, not passed' { $re = Invoke-Apply -Spec $spEmpty -ExpectPlan $dEmpty.Digest -BackupRoot $bk -Stage 'AclEntries'; ($dEmpty.Plan.Count -eq 0) -and ($re.message -like 'REFUSED`[empty-plan`]*') }
        & $T 'empty-plan: toggle off, the same empty plan reads as a PASS - the false PASS the lock prevents' { $re2 = & $With @('empty-plan') { Invoke-Apply -Spec $spEmpty -ExpectPlan $dEmpty.Digest -BackupRoot $bk -Stage 'AclEntries' }; $re2.ok }
        & $T 'empty-plan: a verify with no steps is not a PASS' { -not (Invoke-VerifyRun $spEmpty (Test-Elevated) 20 'AclEntries').ok }
        & $T 'digest: bound to the script itself - the same state under a different script hash gives a different digest' { $dg1 = Get-PlanDigest $fx8.Spec $d8.Plan 'Accounts'; $script:ScriptShaOverride = 'A' * 64; try { $dg2 = Get-PlanDigest $fx8.Spec $d8.Plan 'Accounts' } finally { $script:ScriptShaOverride = $null }; ($dg1 -ceq $d8.Digest) -and ($dg2 -cne $dg1) }
        $okRes = [ordered]@{ verdict = 'PASS'; code = 0; steps = @(); scans = @(); collateral = @(); missing = 0; backupDir = $null; message = '' }
        & $T 'stage 1 closing line says what it examined: the 7 objects, and that access lists and ~/.codex were not' { $tx1 = (Write-ApplyResult $okRes 'Accounts' *>&1 | Out-String); $tx1.Contains('7 pinned objects') -and $tx1.Contains('not examined by this stage') -and -not $tx1.Contains('read-back') -and -not $tx1.Contains('scan of every object') }
        & $T 'stage 2 closing line claims the read-back (probe discriminates)' { (Write-ApplyResult $okRes 'All' *>&1 | Out-String).Contains('read-back') }
        & $T 'stage 1: the live state read for it holds no access list' { (Get-LiveState $fx8.Spec (Test-Elevated) $true 'Accounts').acl.Count -eq 0 }
        & $T 'stage 1: the plan text says no access list is read or changed and prints no access-entry section' { $tx = (Write-Plan $fx8.Spec $d8.State $d8.Plan $d8.Findings $d8.Digest 'Accounts' *>&1 | Out-String); $tx.Contains('no access list is read or changed') -and -not $tx.Contains('WHAT THE ACCESS-ENTRY STEPS ALSO DO') -and $tx.Contains('NOT PART OF THIS STAGE') }
        & $T 'stage 1: the full plan digest is refused for it and nothing changes' { $r = Invoke-Apply -Spec $fx8.Spec -ExpectPlan $d8all.Digest -BackupRoot $bk -Stage 'Accounts'; ($r.message -like 'REFUSED`[plan-digest`]*') -and (& $exists.user $fx8.Ua) }
        & $T 'stage 2 on the real spec: refused before anything else' { $r = Invoke-Apply -Spec $real -ExpectPlan 'x' -BackupRoot $bk -IsAdmin $true -Stage 'AclEntries'; $r.message -like 'REFUSED`[acl-stage-blocked`]*' }
        & $T 'stage 2 on the real spec: toggle off, the next independent lock (selftest-no-real) still refuses' { & $With @('acl-stage-blocked') { $r = Invoke-Apply -Spec $real -ExpectPlan 'x' -BackupRoot $bk -IsAdmin $true -Stage 'All'; $r.message -like 'REFUSED`[selftest-no-real`]*' } }
        $r8 = Invoke-Apply -Spec $fx8.Spec -ExpectPlan $d8.Digest -BackupRoot $bk -Stage 'Accounts'
        & $T 'stage 1: apply passes with exit 0' { $r8.ok -and ($r8.code -eq 0) -and ($r8.verdict -eq 'PASS') }
        & $T 'stage 1: accounts, group, rules and values are gone' { -not (& $exists.user $fx8.Ua) -and -not (& $exists.user $fx8.Ub) -and -not (& $exists.group $fx8.Group) -and -not (& $exists.fw $fx8.Spec.Firewall[0].Name) -and -not (& $exists.fw $fx8.Spec.Firewall[1].Name) -and ((Get-Item $fx8.Spec.Registry.Path).GetValueNames() -cnotcontains $fx8.Ua) }
        & $T 'stage 1: look-alike account, group, rule and value, and the same value name under another key, survive' { (& $exists.user $laU) -and (& $exists.group $laG) -and (& $exists.fw $laR) -and ((Get-Item "$($fx8.RegRoot)\OtherKey").GetValueNames() -ccontains $fx8.Ua) -and ((Get-Item $fx8.Spec.Registry.Path).GetValueNames() -ccontains $laU) -and (& $exists.fw $fx8.Bystander) }
        & $T 'stage 1: every access list is byte-identical afterwards' { $now8 = (@($fx8.Spec.AclTargets | ForEach-Object { (Get-AclAccess $_.Path).GetSecurityDescriptorSddlForm('Access') })) -join "`n"; $now8 -ceq $aclSddl8 }
        & $T 'stage 1: no tree snapshot, preserve list or scan was made' { (-not (Test-Path "$($r8.backupDir)\tree-snapshot.tsv")) -and (-not (Test-Path "$($r8.backupDir)\preserve.tsv")) -and ($r8.scans.Count -eq 0) -and ($null -eq $script:LastSnapshot) }
        & $T 'stage 1: the backup holds backup.json and an undo note that says no access list was read' { (Test-Path "$($r8.backupDir)\backup.json") -and ((Get-Content "$($r8.backupDir)\undo-commands.txt" -Raw).Contains('no access list was read, changed or recorded')) -and -not ((Get-Content "$($r8.backupDir)\undo-commands.txt" -Raw).Contains('AddAccessRule')) }
        & $T 'stage 1: report.json records the stage' { (Get-Content "$($r8.backupDir)\report.json" -Raw | ConvertFrom-Json).stage -ceq 'Accounts' }
        & $T 'stage 1: verify passes for it, and still fails for the full plan (probe discriminates)' { (Invoke-VerifyRun $fx8.Spec (Test-Elevated) 60 'Accounts').ok -and -not (Invoke-VerifyRun $fx8.Spec (Test-Elevated) 60 'All').ok }
        & $T 'stage 1: a second run changes nothing and passes' { $dr8 = Invoke-DryRun $fx8.Spec (Test-Elevated) 'Accounts'; $r8b = Invoke-Apply -Spec $fx8.Spec -ExpectPlan $dr8.Digest -BackupRoot $bk -Stage 'Accounts'; $r8b.ok -and (@($r8b.steps | Where-Object { $_.result -ne 'already gone' }).Count -eq 0) }
        # a group left with no members (both accounts deleted, as after a stop at the group step) is empty, not unreadable
        $fxo = New-Fixture 'f8o'
        Remove-LocalUser -SID (Get-LocalUser $fxo.Ua).SID; Remove-LocalUser -SID (Get-LocalUser $fxo.Ub).SID
        & $T 'group members: an empty group reads as empty, not as unreadable' { $gm = @(Get-GroupMemberSids $fxo.Group); ($gm.Count -eq 0) -and (@((Get-GroupState $fxo.Spec).memberSids).Count -eq 0) }
        & $T 'group members: the expression used before turned an empty group into unreadable (probe discriminates)' { $m = try { @(Get-LocalGroupMember -Group $fxo.Group -ErrorAction Stop) } catch { $null }; $null -eq $m }
        & $T 'group members: a missing group reads as unreadable, never as empty' { (Get-GroupMemberSids "$($script:Own)no-such-group") -ccontains 'unreadable' }
        # refusals at the apply level, one unexpected state at a time (each reverted before the next)
        $fx9 = New-Fixture 'f9'; $sp9 = $fx9.Spec; $d9 = Invoke-DryRun $sp9 (Test-Elevated) 'Accounts'
        $refuseNow = { $dN = Invoke-DryRun $sp9 (Test-Elevated) 'Accounts'; $rN = Invoke-Apply -Spec $sp9 -ExpectPlan $dN.Digest -BackupRoot $bk -Stage 'Accounts'; ($rN.message -like 'REFUSED`[unexpected-live`]*') -and (& $exists.user $fx9.Ua) -and (& $exists.user $fx9.Ub) -and (& $exists.group $fx9.Group) -and (& $exists.fw $sp9.Firewall[0].Name) }
        Set-NetFirewallRule -Name $sp9.Firewall[0].Name -LocalUser "D:(A;;CC;;;$($sp9.Users[0].Sid))(A;;CC;;;$($sp9.Users[1].Sid))"
        & $T 'stage 1 refusal: a rule scoped to the account plus another SID' $refuseNow
        Set-NetFirewallRule -Name $sp9.Firewall[0].Name -LocalUser "D:(A;;CC;;;$($sp9.Users[0].Sid))"
        New-Item -ItemType Directory -Path "$($sp9.ProfileFolderRoot)\$($fx9.Ua)" -Force | Out-Null
        & $T 'stage 1 refusal: an account with a profile folder' $refuseNow
        Remove-Item -LiteralPath "$($sp9.ProfileFolderRoot)\$($fx9.Ua)" -Recurse -Force
        New-NetFirewallRule -Name "$($script:Own)fwid-f9-extra" -DisplayName "$($script:Own)fw-f9-extra" -Direction Outbound -Action Block -Protocol TCP -RemoteAddress '127.0.0.0/8' -Enabled False | Out-Null; $script:Created.Add("fw:$($script:Own)fwid-f9-extra")
        & $T 'stage 1 refusal: another rule that matches the rule glob (the Offline account''s other rules)' $refuseNow
        Remove-NetFirewallRule -Name "$($script:Own)fwid-f9-extra"
        $ux9 = "$($script:Own)ux-9"; New-LocalUser -Name $ux9 -Password $pw -Disabled | Out-Null; $script:Created.Add("user:$ux9"); Add-LocalGroupMember -Group $fx9.Group -Member $ux9
        & $T 'stage 1 refusal: a group member that is not on the allowlist' $refuseNow
        Remove-LocalGroupMember -Group $fx9.Group -Member $ux9
        $d9b = Invoke-DryRun $sp9 (Test-Elevated) 'Accounts'; $r9 = Invoke-Apply -Spec $sp9 -ExpectPlan $d9b.Digest -BackupRoot $bk -Stage 'Accounts'
        & $T 'stage 1 refusal: with the unexpected states reverted the same fixture applies, and the foreign account survives' { $r9.ok -and -not (& $exists.user $fx9.Ua) -and (& $exists.user $ux9) }
        # killed at each phase: the earlier steps stay done, the rest untouched, and a second run completes
        foreach ($kid in 'D1', 'A5', 'A4', 'A1', 'A3') {
            $kk = $kid; $fxk = New-Fixture "k$kk"; Enable-LocalUser -Name $fxk.Ua; Enable-LocalUser -Name $fxk.Ub; $dk = Invoke-DryRun $fxk.Spec (Test-Elevated) 'Accounts'
            $script:StepFault = { param($st) if ($st.id -eq $kk) { throw 'killed here' } }.GetNewClosure()
            $rk = Invoke-Apply -Spec $fxk.Spec -ExpectPlan $dk.Digest -BackupRoot $bk -Stage 'Accounts'
            $script:StepFault = $null
            & $T "stage 1 killed at $kk`: exit 3, earlier steps done, the rest untouched" {
                $fwGone = @('A4', 'A1', 'A3') -ccontains $kk; $regGone = @('A1', 'A3') -ccontains $kk; $usrGone = @('A3') -ccontains $kk
                ($rk.code -eq 3) -and ((-not (& $exists.fw $fxk.Spec.Firewall[0].Name)) -eq $fwGone) -and ((-not (& $exists.fw $fxk.Spec.Firewall[1].Name)) -eq $fwGone) -and (((Get-Item $fxk.Spec.Registry.Path).GetValueNames() -cnotcontains $fxk.Ua) -eq $regGone) -and ((-not (& $exists.user $fxk.Ua)) -eq $usrGone) -and (& $exists.group $fxk.Group) }
            & $T "stage 1 killed at $kk`: the accounts are already disabled (they are not yet when killed at the very first step), so nothing half-done leaves a usable account" {
                if ($kk -ceq 'A3') { -not (& $exists.user $fxk.Ua) }
                else { $wantOff = ($kk -cne 'D1'); ((-not (Get-LocalUser -Name $fxk.Ua).Enabled) -eq $wantOff) -and ((-not (Get-LocalUser -Name $fxk.Ub).Enabled) -eq $wantOff) } }
            & $T "stage 1 killed at $kk`: running it again completes" { $drk = Invoke-DryRun $fxk.Spec (Test-Elevated) 'Accounts'; $r2k = Invoke-Apply -Spec $fxk.Spec -ExpectPlan $drk.Digest -BackupRoot $bk -Stage 'Accounts'; ($r2k.code -eq 0) -and ((Get-Content "$($r2k.backupDir)\undo-commands.txt" -Raw).Contains($rk.backupDir)) -and -not (& $exists.user $fxk.Ua) -and -not (& $exists.user $fxk.Ub) -and -not (& $exists.group $fxk.Group) -and -not (& $exists.fw $fxk.Spec.Firewall[0].Name) -and ((Get-Item $fxk.Spec.Registry.Path).GetValueNames() -cnotcontains $fxk.Ua) }
        }
        # a step that fails stops the run: later steps are untouched
        $fx3 = New-Fixture 'f3'
        $d3 = Invoke-DryRun $fx3.Spec (Test-Elevated)
        $script:StepFault = { param($st) if ($st.id -eq 'A9') { throw 'injected fault' } }
        $r3 = Invoke-Apply -Spec $fx3.Spec -ExpectPlan $d3.Digest -BackupRoot $bk
        $script:StepFault = $null
        & $T 'step failure: exit code 3, FAIL, and the message names the step' { ($r3.code -eq 3) -and ($r3.verdict -eq 'FAIL') -and ($r3.message -like '*A9*') }
        & $T 'step failure: steps before it were done' { ((Get-SidAces "$($fx3.Root)\repo" $fx3.CapA).Count -eq 0) -and ((Get-SidAces "$($fx3.Root)\repo\.git" $fx3.CapB).Count -eq 0) }
        & $T 'step failure: steps after it were not touched' { ((Get-SidAces "$($fx3.Root)\ovms" $fx3.CapB).Count -gt 0) -and (& $exists.user $fx3.Ua) -and (& $exists.group $fx3.Group) -and (& $exists.fw $fx3.Spec.Firewall[0].Name) }
        & $T 'step failure: report.json records FAIL' { (Get-Content "$($r3.backupDir)\report.json" -Raw | ConvertFrom-Json).verdict -ceq 'FAIL' }
        # ---- the real accounts are untouched
        & $T 'real objects: no simulated or real destructive call reached them' { $script:SimLog.Count -eq 0 }
    } catch {
        $results.Add([ordered]@{ test = 'self-test ran to the end'; pass = $false; detail = "stopped: $($_.Exception.Message) at line $($_.InvocationInfo.ScriptLineNumber)" })
    } finally {
        $script:SimulateOnly = $false; $script:GatesOff = @(); $script:BackupTamper = $null
        $clean = Remove-Throwaway
        $left = [System.Collections.Generic.List[string]]::new()
        foreach ($u in Get-LocalUser | Where-Object { $_.Name.StartsWith($script:Own, 'Ordinal') }) { $left.Add("user $($u.Name)") }
        foreach ($g in Get-LocalGroup | Where-Object { $_.Name.StartsWith($script:Own, 'Ordinal') }) { $left.Add("group $($g.Name)") }
        foreach ($r in Get-NetFirewallRule | Where-Object { $_.Name.StartsWith($script:Own, 'Ordinal') }) { $left.Add("rule $($r.Name)") }
        foreach ($k in Get-ChildItem 'HKCU:\Software' | Where-Object { $_.PSChildName.StartsWith($script:Own, 'Ordinal') }) { $left.Add("key $($k.PSChildName)") }
        foreach ($d in Get-ChildItem $script:ThrowRoot -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith($script:Own, 'Ordinal') }) { $left.Add("folder $($d.FullName)") }
        $script:SelfTestActive = $false
        $script:AdminTempRoot = $adminTempWas
        $script:Own = $ownWas
        $env:ProgramData = $pdWas
    }
    $fail = @($results | Where-Object { -not $_.pass })
    Write-Host ''
    foreach ($x in $results) { Write-Host ("  {0}  {1}{2}" -f $(if ($x.pass) { 'PASS' } else { 'FAIL' }), $x.test, $(if ($x.detail) { "  -> $($x.detail)" } else { '' })) -ForegroundColor $(if ($x.pass) { 'Green' } else { 'Red' }) }
    Write-Host ''
    Write-Host ("Self-test: {0} checks, {1} failed." -f $results.Count, $fail.Count)
    Write-Host ("Throwaway objects created: {0}" -f $script:Created.Count)
    Write-Host ("Throwaway objects removed: {0}" -f $clean.removed.Count)
    $clean.removed | ForEach-Object { Write-Host "    removed $_" }
    $clean.failed | ForEach-Object { Write-Host "    COULD NOT REMOVE $_" -ForegroundColor Red }
    Write-Host ("Throwaway objects left behind: {0}" -f $left.Count)
    $left | ForEach-Object { Write-Host "    LEFT $_" -ForegroundColor Red }
    return [ordered]@{ ok = ($fail.Count -eq 0 -and $left.Count -eq 0 -and $clean.failed.Count -eq 0); checks = $results.Count; failed = $fail.Count; left = $left.Count }
}

# ---------------------------------------------------------------- entry

function Write-ApplyResult($Res, [string]$Stage = 'All') {
    Write-Host ''
    if ($Res.verdict -eq 'PASS') {
        if (Test-StageHas $Stage 'Acl') {
            Write-Host 'PASS: the Codex entries are cut out of every object in the BlarAI folder, Temp and C:\ovms, a read-back of every object found nothing else changed, and the accounts, group, rules and values on the allowlist are gone.' -ForegroundColor Green
        } else {
            Write-Host 'PASS: the 7 pinned objects (2 accounts, 1 group, 2 firewall rules, 2 hidden-user values) are gone. Access-list entries and ~/.codex were not examined by this stage.' -ForegroundColor Green
        }
    } elseif ($Res.code -eq 2) {
        Write-Host 'NOTHING WAS CHANGED.' -ForegroundColor Yellow
        Write-Host $Res.message -ForegroundColor Yellow
    } else {
        Write-Host 'FAIL: the machine is not in the target state.' -ForegroundColor Red
        Write-Host $Res.message -ForegroundColor Red
    }
    foreach ($s in $Res.steps) { Write-Host ("  [{0}] {1}: {2}" -f $s.id, $s.target, $s.result) }
    foreach ($sc in $Res.scans) { Write-Host ("  read back {0}: {1} objects, {2} unreadable, {3} still carrying a Codex SID, {4} folders left at the time cap" -f $sc.root, $sc.scanned, $sc.unreadable, $sc.hits, $sc.foldersLeftUnscanned) }
    if ($Res.collateral.Count) { Write-Host "  $($Res.collateral.Count) object(s) differ from their before-change list in more than the removed Codex entries; list: collateral.txt in the backup folder." -ForegroundColor Yellow }
    if ($Res.missing) { Write-Host "  Note: $($Res.missing) recorded object(s) were no longer there at the read-back (deleted meanwhile, or replaced); count only, in report.json." -ForegroundColor Yellow }
    if ($Res.backupDir) {
        Write-Host ''
        Write-Host "Backup and report: $($Res.backupDir)  (SYSTEM and Administrators only)"
        if (Test-StageHas $Stage 'Acl') { Write-Host 'To put the access lists back exactly: -RestoreAcl <that folder> (see undo-commands.txt). Firewall rules and registry values can be recreated from undo-commands.txt.' }
        else { Write-Host 'To recreate a firewall rule or a registry value, use the lines in undo-commands.txt there.' }
        Write-Host 'Deleted accounts and the group cannot be restored.'
    }
}

function Invoke-Main {
    $modes = @($Apply, $Verify, $Guided, $SelfTest, [bool]$RestoreAcl) | Where-Object { $_ }
    if ($modes.Count -gt 1) { Write-Host 'Choose one mode.' -ForegroundColor Red; return 2 }
    if ($DryRun -and $modes.Count) { Write-Host '-DryRun cannot be combined with another mode (it would be ignored). Choose one mode.' -ForegroundColor Red; return 2 }
    $script:ProgressOn = -not $SelfTest
    $isAdmin = Test-Elevated
    if ($SelfTest) {
        if (-not $isAdmin) { Write-Host 'The self-test needs an administrator shell (it creates throwaway accounts).' -ForegroundColor Red; return 2 }
        $r = Invoke-SelfTest
        return $(if ($r.ok) { 0 } else { 1 })
    }
    $spec = Get-RealSpec
    try { Assert-SpecAllowed $spec } catch { Write-Host $_.Exception.Message -ForegroundColor Red; return 2 }
    if ($RestoreAcl) {
        try {
            $rr = Invoke-RestoreAcl $spec $RestoreAcl $RestorePath $isAdmin
            Write-Host ("Restored {0} object(s); {1} already as recorded; {2} problem(s)." -f $rr.restored, $rr.alreadyAsRecorded, $rr.problems.Count)
            $rr.problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
            return $(if ($rr.problems.Count) { 1 } else { 0 })
        } catch { Write-Host $_.Exception.Message -ForegroundColor Red; return 2 }
    }
    $stuck = @(Get-IncompleteRuns $spec $BackupRoot)
    if ($stuck.Count -and (Test-StageHas $Stage 'Acl')) { Write-Host ("NOTE: an earlier apply did not finish cleanly: " + ($stuck -join '; ') + ". Use -ResumeFrom <that folder>.") -ForegroundColor Yellow }
    if ($Verify) {
        $v = Invoke-VerifyRun $spec $isAdmin $ScanSeconds $Stage
        Write-Host ''
        if ($v.ok) { Write-Host $(if (Test-StageHas $Stage 'Acl') { 'PASS: none of the pinned objects remain and no object in the three trees carries a Codex SID.' } else { 'PASS: the 7 pinned objects (accounts, group, firewall rules, hidden-user values) are gone. Access-list entries and ~/.codex were not examined by this stage.' }) -ForegroundColor Green } else { Write-Host 'FAIL: leftovers remain.' -ForegroundColor Red; $v.problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red } }
        foreach ($s in $v.scans) { Write-Host ("  scanned {0}: {1} objects in {2}s, {3} hits" -f $s.root, $s.scanned, $s.seconds, $s.hits) }
        $v.notes | ForEach-Object { Write-Host "  note: $_" -ForegroundColor Yellow }
        return $(if ($v.ok) { 0 } else { 1 })
    }
    if ($Apply) {
        $res = Invoke-Apply -Spec $spec -ExpectPlan $ExpectPlan -BackupRoot $BackupRoot -IsAdmin $isAdmin -ScanSecs $ScanSeconds -SnapSecs $SnapshotSeconds -Stage $Stage -ResumeFrom $ResumeFrom
        Write-ApplyResult $res $Stage
        return $res.code
    }
    if (($Guided) -and (Test-StageHas $Stage 'Acl') -and (Test-Gate 'acl-stage-blocked')) { Write-Host 'The access-entry stage is not enabled for the real machine. Use -Stage Accounts.' -ForegroundColor Red; return 2 }
    $d = Invoke-DryRun $spec $isAdmin $Stage
    Write-Plan $spec $d.State $d.Plan $d.Findings $d.Digest $Stage
    if (-not $Guided) {
        Write-Host ''
        Write-Host 'Dry run only. Nothing was changed. To apply: -Apply -ExpectPlan <digest above>.'
        return 0
    }
    if (-not $isAdmin) { Write-Host 'Applying needs an administrator shell.' -ForegroundColor Red; return 2 }
    if ($d.Findings.Count) { Write-Host 'Nothing was changed.' -ForegroundColor Yellow; return 2 }
    Write-Host ''
    $answer = Read-Host 'Type APPLY (capitals) to carry out this plan, or anything else to stop'
    if ($answer -cne 'APPLY') { Write-Host 'Stopped. Nothing was changed.'; return 0 }
    $res = Invoke-Apply -Spec $spec -ExpectPlan $d.Digest -BackupRoot $BackupRoot -IsAdmin $isAdmin -ScanSecs $ScanSeconds -SnapSecs $SnapshotSeconds -Stage $Stage -ResumeFrom $ResumeFrom
    Write-ApplyResult $res $Stage
    return $res.code
}

if ($MyInvocation.InvocationName -ne '.') {
    $code = 3
    try {
        $myHash = Get-NormalisedSha256 $PSCommandPath
        if (@('Accounts', 'AclEntries', 'All') -cnotcontains $Stage) {
            Write-Host "REFUSED: unknown -Stage '$Stage' (use Accounts, AclEntries or All). Nothing was changed." -ForegroundColor Red
            $code = 2
        } elseif ($ExpectScriptSha256 -and ($myHash -ine $ExpectScriptSha256)) {
            Write-Host "REFUSED: this script's SHA-256 ($myHash) is not the one the launcher computed ($ExpectScriptSha256); it was changed after the launcher read it." -ForegroundColor Red
            $code = 2
        } else {
            if (-not $SelfTest) { Write-Host "Script SHA-256: $myHash" }
            $code = @(Invoke-Main)[-1]
        }
    }
    catch { Write-Host ("Unexpected error: " + $_.Exception.Message) -ForegroundColor Red; $code = 3 }
    finally {
        if ($HoldOpen) {
            $meaning = switch ($code) { 0 { 'done or nothing to do' } 1 { 'FAIL: the machine is not in the target state' } 2 { 'refused or stopped before any change' } 3 { 'stopped part-way or an unexpected error' } default { 'unexpected' } }
            Write-Host ''
            Write-Host "Exit code $code ($meaning)." -ForegroundColor Cyan
            Read-Host 'Press Enter to close this window' | Out-Null
        }
    }
    exit $code
}
