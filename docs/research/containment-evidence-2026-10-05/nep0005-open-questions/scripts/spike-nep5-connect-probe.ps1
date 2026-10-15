#requires -Version 5.1
<#
.SYNOPSIS
  NEP-0005 matrix: the code that runs AS the blarai-spike account for this matrix, started by the matrix with a session password (CreateProcessWithLogonW: an interactive-type logon with the account's profile
  loaded, NOT the batch logon the account's scheduled task uses) and an explicit minimal environment block. The account's scheduled task is never edited or started by this script.
  Self-contained (no dot-sourcing): the matrix copies it into C:\blarai-spike\bin, which the account can read but not write. The existing spike-run-test.ps1 is hash-bound and connects to ONE configured IPv4
  target; this script makes the connects the matrix needs.

.DESCRIPTION
  Modes (from the operator-written request file, never from the account):
    identity  the token SID and nothing else (proves the task starts and logs on as the account; no network)
    connect   one TCP connect per target to 127.0.0.1:<port> or [::1]:<port>, each result recorded with the Windows socket error code
              (10013 = blocked by a filter; 10061 = refused: nothing listening; 10060 = timeout)
    direct    (N1 only) ONE direct WFP call from this account's own standard token, no harness: `add` = a single FwpmFilterAdd0 of a BLOCK filter for THIS account's SID in the S2
              sublayer under our provider (fixed key, no explicit transaction, so the verdict is the add call's own status); `delete` = a single FwpmFilterDeleteByKey0 of one fixed
              test filter key. The engine's status is recorded verbatim (phase open|call and the hex code). The request carries only the op; the SID is the token's own, the sublayer,
              provider and keys are constants here. Anything else is refused before the engine is opened.
  Fail-closed: a request that does not validate writes an error result and runs nothing. Ports are 1024..65535 integers; the host is a fixed literal; a result file is
  always written. -SelfTest runs the pure helpers, the C# guards (compile and validate only) and local loopback sockets: no WFP call, no task.
#>
[CmdletBinding()]
param(
    [string]$RequestFile,
    [string]$ConfigFile,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
if (-not $ConfigFile) { $ConfigFile = Join-Path $PSScriptRoot 'spike-config.json' }
$script:MaxTargets = 12

# fixed by the matrix's recorded constants (spike-nep5-lib.ps1): S2, our provider, the two N1 keys
$script:DirectCSharp = @'
namespace BlarAI.Nep5Probe
{
    using System;
    using System.Collections.Generic;
    using System.Runtime.InteropServices;
    using System.Security.AccessControl;
    using System.Security.Principal;

    [StructLayout(LayoutKind.Sequential)] public struct BLOB { public uint size; public IntPtr data; }
    [StructLayout(LayoutKind.Sequential)] public struct VAL { public uint type; public IntPtr value; }
    [StructLayout(LayoutKind.Sequential)] public struct DD { public IntPtr name; public IntPtr description; }
    [StructLayout(LayoutKind.Sequential)] public struct SESSION { public Guid sessionKey; public DD displayData; public uint flags; public uint txnWaitTimeoutInMSec; public uint processId; public IntPtr sid; public IntPtr username; public int kernelMode; }
    [StructLayout(LayoutKind.Sequential)] public struct ACTION { public uint type; public Guid filterType; }
    [StructLayout(LayoutKind.Sequential)] public struct COND { public Guid fieldKey; public uint matchType; public VAL conditionValue; }
    [StructLayout(LayoutKind.Sequential)] public struct CTX { public ulong a; public ulong b; }
    [StructLayout(LayoutKind.Sequential)]
    public struct FILTER
    {
        public Guid filterKey; public DD displayData; public uint flags; public IntPtr providerKey; public BLOB providerData; public Guid layerKey; public Guid subLayerKey;
        public VAL weight; public uint numFilterConditions; public IntPtr filterCondition; public ACTION action; public CTX context; public IntPtr reserved; public ulong filterId; public VAL effectiveWeight;
    }

    public static class Direct
    {
        [DllImport("fwpuclnt.dll", CharSet = CharSet.Unicode)] static extern uint FwpmEngineOpen0(string serverName, uint authnService, IntPtr authIdentity, ref SESSION session, out IntPtr engineHandle);
        [DllImport("fwpuclnt.dll")] static extern uint FwpmEngineClose0(IntPtr engineHandle);
        [DllImport("fwpuclnt.dll")] static extern uint FwpmFilterAdd0(IntPtr engineHandle, ref FILTER filter, IntPtr sd, out ulong id);
        [DllImport("fwpuclnt.dll")] static extern uint FwpmFilterDeleteByKey0(IntPtr engineHandle, ref Guid key);

        public static readonly Guid S2 = new Guid("3e29ae7e-fd9f-413a-8b8d-da9bd3a96359");
        public static readonly Guid Provider = new Guid("3e29ae7e-fd9f-413a-8b8d-da9bd3a96360");
        public static readonly Guid AddKey = new Guid("f1763001-0000-4d8e-9a31-2b6d4c8e0021");
        public static readonly Guid DeleteKey = new Guid("f1763001-0000-4d8e-9a31-2b6d4c8e0001");
        static readonly Guid LayerV4 = new Guid("c38d57d1-05a7-4c33-904f-7fbceee60e82");
        static readonly Guid CondUser = new Guid("af043a0a-b34d-4f86-979c-c90371af6e66");

        // Every refusal is in front of the engine: null = allowed.
        public static string CheckAdd(string sid, string ownSid, Guid sublayer, Guid key)
        {
            if (string.IsNullOrEmpty(sid) || sid != ownSid) return "the SID must be this token's own SID";
            if (System.Text.RegularExpressions.Regex.IsMatch(sid, "^S-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]{3,}$") == false) return "not an account-domain user SID";
            if (sublayer != S2) return "only the S2 sublayer";
            if (key != AddKey) return "only the fixed N1 add key";
            return null;
        }
        public static string CheckDelete(Guid sublayer, Guid key)
        {
            if (sublayer != S2) return "only the S2 sublayer";
            if (key != DeleteKey) return "only the fixed N1 test filter key";
            return null;
        }

        static byte[] BuildSd(string sid)
        {
            RawAcl acl = new RawAcl(2, 1);
            acl.InsertAce(0, new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, 1, new SecurityIdentifier(sid), false, null));
            RawSecurityDescriptor sd = new RawSecurityDescriptor(ControlFlags.DiscretionaryAclPresent, null, null, null, acl);
            byte[] b = new byte[sd.BinaryLength]; sd.GetBinaryForm(b, 0); return b;
        }

        static string[] Open(out IntPtr h)
        {
            SESSION s = new SESSION(); s.flags = 0; s.txnWaitTimeoutInMSec = 10000;
            uint rc = FwpmEngineOpen0(null, 0xFFFFFFFF, IntPtr.Zero, ref s, out h);
            return rc == 0 ? null : new string[] { "open", "0x" + rc.ToString("X8") };
        }

        // ONE FwpmFilterAdd0, no explicit transaction: the status is the add call's own.
        public static string[] Add(string ownSid)
        {
            string bad = CheckAdd(ownSid, WindowsIdentity.GetCurrent().User.Value, S2, AddKey);
            if (bad != null) return new string[] { "refused", bad };
            List<IntPtr> allocs = new List<IntPtr>();
            IntPtr h = IntPtr.Zero;
            try
            {
                byte[] sd = BuildSd(ownSid);
                IntPtr d = Marshal.AllocHGlobal(sd.Length); allocs.Add(d); Marshal.Copy(sd, 0, d, sd.Length);
                BLOB blob = new BLOB(); blob.size = (uint)sd.Length; blob.data = d;
                IntPtr bp = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(BLOB))); allocs.Add(bp); Marshal.StructureToPtr(blob, bp, false);
                COND c = new COND(); c.fieldKey = CondUser; c.matchType = 0; c.conditionValue.type = 14; c.conditionValue.value = bp;
                IntPtr cp = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(COND))); allocs.Add(cp); Marshal.StructureToPtr(c, cp, false);
                IntPtr pk = Marshal.AllocHGlobal(16); allocs.Add(pk); Marshal.StructureToPtr(Provider, pk, false);
                IntPtr wp = Marshal.AllocHGlobal(8); allocs.Add(wp); Marshal.WriteInt64(wp, 0x1000);
                IntPtr nm = Marshal.StringToHGlobalUni("BlarAI #1763 n1-add-attempt"); allocs.Add(nm);
                FILTER f = new FILTER(); f.filterKey = AddKey; f.displayData.name = nm; f.flags = 1; f.providerKey = pk; f.layerKey = LayerV4; f.subLayerKey = S2;
                f.weight.type = 4; f.weight.value = wp; f.numFilterConditions = 1; f.filterCondition = cp; f.action.type = 0x1001;
                string[] o = Open(out h); if (o != null) return o;
                ulong id; uint rc = FwpmFilterAdd0(h, ref f, IntPtr.Zero, out id);
                return new string[] { "call", "0x" + rc.ToString("X8") };
            }
            finally { if (h != IntPtr.Zero) FwpmEngineClose0(h); foreach (IntPtr p in allocs) Marshal.FreeHGlobal(p); }
        }

        // ONE FwpmFilterDeleteByKey0.
        public static string[] Delete()
        {
            string bad = CheckDelete(S2, DeleteKey);
            if (bad != null) return new string[] { "refused", bad };
            IntPtr h = IntPtr.Zero;
            try
            {
                string[] o = Open(out h); if (o != null) return o;
                Guid k = DeleteKey; uint rc = FwpmFilterDeleteByKey0(h, ref k);
                return new string[] { "call", "0x" + rc.ToString("X8") };
            }
            finally { if (h != IntPtr.Zero) FwpmEngineClose0(h); }
        }
    }
}
'@

function Get-Now { (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }

function Test-ProbePort($Value, [int]$Min = 1024) {
    # An unprivileged TCP port as an integer; anything else (string, float, out of range) is refused. $Min is a parameter only so the self-test can switch the floor off.
    return (($Value -is [int] -or $Value -is [long]) -and $Value -ge $Min -and $Value -le 65535)
}

function Test-ProbeRequest {
    # PURE. Returns the problems of a parsed request (empty = valid): run id shape, a known mode, targets (family v4|v6, a good port, at most 12), timeout 500..10000,
    # and for direct mode exactly one op, add or delete, and nothing else.
    param($Req, [int]$PortMin = 1024)
    $p = New-Object System.Collections.ArrayList
    if ($Req -eq $null) { return @('no request') }
    if ([string]$Req.run_id -notmatch '^[A-Za-z0-9-]{8,64}$') { [void]$p.Add('run_id malformed') }
    if ([string]$Req.mode -notin @('identity', 'connect', 'direct')) { [void]$p.Add("mode '$($Req.mode)' is not identity, connect or direct") }
    $to = $Req.timeout_ms
    if (-not (($to -is [int] -or $to -is [long]) -and $to -ge 500 -and $to -le 10000)) { [void]$p.Add('timeout_ms must be an integer 500..10000') }
    if ([string]$Req.mode -eq 'connect') {
        $t = @($Req.targets)
        if ($t.Count -lt 1 -or $t.Count -gt $script:MaxTargets) { [void]$p.Add("connect mode needs 1..$($script:MaxTargets) targets") }
        foreach ($x in $t) {
            if ([string]$x.family -notin @('v4', 'v6')) { [void]$p.Add("target family '$($x.family)' is not v4 or v6") }
            if (-not (Test-ProbePort $x.port $PortMin)) { [void]$p.Add("target port '$($x.port)' is not an integer 1024..65535") }
        }
    }
    if ([string]$Req.mode -eq 'direct') {
        if (-not $Req.direct -or [string]$Req.direct.op -cnotin @('add', 'delete')) { [void]$p.Add('direct mode needs direct.op = add or delete') }
        elseif (@($Req.direct.PSObject.Properties).Count -ne 1) { [void]$p.Add('direct carries the op and nothing else') }
    }
    return @($p)
}

function Get-DirectVerdict {
    # PURE. succeeded | denied | open_failed | compile_failed | refused | other, from the phase and the engine's hex status. Denied = ERROR_ACCESS_DENIED (0x5) or E_ACCESS_DENIED
    # (0x80070005) at the CALL (never at the open, which proves nothing about the write).
    param([string]$Phase, [string]$RcHex)
    switch ($Phase) {
        'call' { if ($RcHex -eq '0x00000000') { return 'succeeded' }; if ($RcHex -in @('0x00000005', '0x80070005')) { return 'denied' }; return 'other' }
        'open' { return 'open_failed' } 'compile' { return 'compile_failed' } 'refused' { return 'refused' } default { return 'other' }
    }
}

function Get-ConnectOutcome {
    # PURE. connected | blocked | refused | timeout | error from a connect attempt's result.
    param([bool]$Connected, [int]$Win32, [bool]$TimedOut)
    if ($Connected) { return 'connected' }
    if ($TimedOut) { return 'timeout' }
    switch ($Win32) { 10013 { return 'blocked' } 10061 { return 'refused' } 10060 { return 'timeout' } default { return 'error' } }
}

function Invoke-ProbeConnect {
    # One TCP connect to a FIXED loopback literal (127.0.0.1 or ::1) on $Port. Never throws; the outcome and the Windows socket error code are recorded.
    param([ValidateSet('v4', 'v6')][string]$Family, [int]$Port, [int]$TimeoutMs)
    $addr = if ($Family -eq 'v6') { [Net.IPAddress]::IPv6Loopback } else { [Net.IPAddress]::Loopback }
    $af = if ($Family -eq 'v6') { [Net.Sockets.AddressFamily]::InterNetworkV6 } else { [Net.Sockets.AddressFamily]::InterNetwork }
    $sw = [Diagnostics.Stopwatch]::StartNew(); $s = New-Object Net.Sockets.Socket($af, [Net.Sockets.SocketType]::Stream, [Net.Sockets.ProtocolType]::Tcp)
    $connected = $false; $win32 = 0; $timedOut = $false; $err = ''
    try {
        $iar = $s.BeginConnect((New-Object Net.IPEndPoint($addr, $Port)), $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { try { $s.EndConnect($iar); $connected = $true } catch [Net.Sockets.SocketException] { $win32 = $_.Exception.NativeErrorCode; $err = $_.Exception.Message } }
        else { $timedOut = $true; $win32 = 10060; $err = "timeout ${TimeoutMs}ms" }
    } catch [Net.Sockets.SocketException] { $win32 = $_.Exception.NativeErrorCode; $err = $_.Exception.Message }
    catch { $win32 = -1; $err = $_.Exception.Message }
    finally { try { $s.Close() } catch {} }
    return [ordered]@{ family = $Family; port = $Port; result = (Get-ConnectOutcome -Connected $connected -Win32 $win32 -TimedOut $timedOut); win32 = $win32; ms = $sw.ElapsedMilliseconds; error = $err }
}

function Initialize-DirectType {
    if (-not ('BlarAI.Nep5Probe.Direct' -as [type])) { Add-Type -TypeDefinition $script:DirectCSharp -Language CSharp }
}

function Invoke-DirectCall {
    # The direct mode: compile the C# (as this account), make ONE call, record phase and status verbatim. Never throws.
    param([string]$Op, [string]$OwnSid)
    $o = [ordered]@{ op = $Op; phase = ''; rc_hex = ''; verdict = ''; error = $null }
    try { Initialize-DirectType } catch { $o.phase = 'compile'; $o.error = $_.Exception.Message; $o.verdict = Get-DirectVerdict 'compile' ''; return $o }
    try {
        $r = if ($Op -ceq 'add') { [BlarAI.Nep5Probe.Direct]::Add($OwnSid) } else { [BlarAI.Nep5Probe.Direct]::Delete() }
        $o.phase = [string]$r[0]; $o.rc_hex = [string]$r[1]
    } catch { $o.phase = 'error'; $o.error = $_.Exception.Message }
    $o.verdict = Get-DirectVerdict $o.phase $o.rc_hex
    return $o
}

function Write-ProbeResult {
    # temp + move; UTF-8 without BOM (PowerShell 5.1's Set-Content -Encoding UTF8 writes one).
    param([string]$Path, $Object)
    $tmp = "$Path.tmp"
    [IO.File]::WriteAllText($tmp, (ConvertTo-Json -InputObject $Object -Depth 8), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

if ($SelfTest) {
    $f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    $good = [pscustomobject]@{ run_id = 'nep5-test-0001'; mode = 'connect'; timeout_ms = 3000; targets = @([pscustomobject]@{ family = 'v4'; port = 61763 }, [pscustomobject]@{ family = 'v6'; port = 60085 }) }
    Chk 'request: a well-formed connect request is valid' ((@(Test-ProbeRequest $good)).Count -eq 0)
    $mut = { param($o, $k, $v) $c = $o | ConvertTo-Json -Depth 6 | ConvertFrom-Json; $c.$k = $v; $c }
    Chk 'request: a bad run id, an unknown mode and a timeout outside 500..10000 are each refused' (((@(Test-ProbeRequest (& $mut $good 'run_id' 'x'))).Count -ge 1) -and ((@(Test-ProbeRequest (& $mut $good 'mode' 'shell'))).Count -ge 1) -and ((@(Test-ProbeRequest (& $mut $good 'timeout_ms' 100))).Count -ge 1) -and ((@(Test-ProbeRequest (& $mut $good 'timeout_ms' 99999))).Count -ge 1))
    Chk 'request: ports 80, 70000, "61763" (string), 61763.5 and null are refused; 1024 and 65535 are accepted' ((-not (Test-ProbePort 80)) -and (-not (Test-ProbePort 70000)) -and (-not (Test-ProbePort '61763')) -and (-not (Test-ProbePort 61763.5)) -and (-not (Test-ProbePort $null)) -and (Test-ProbePort 1024) -and (Test-ProbePort 65535))
    $bad80 = [pscustomobject]@{ run_id = 'nep5-test-0002'; mode = 'connect'; timeout_ms = 3000; targets = @([pscustomobject]@{ family = 'v4'; port = 80 }) }
    Chk 'request: a target on port 80 is refused (lock on)' ((@(Test-ProbeRequest $bad80)).Count -ge 1)
    Chk 'request: the same request is ACCEPTED with the port floor switched off (the lock is what refused it)' ((@(Test-ProbeRequest $bad80 -PortMin 1)).Count -eq 0)
    Chk 'request: a family other than v4/v6 and more than 12 targets are refused' (((@(Test-ProbeRequest ([pscustomobject]@{ run_id = 'nep5-test-0003'; mode = 'connect'; timeout_ms = 3000; targets = @([pscustomobject]@{ family = 'v5'; port = 61763 }) }))).Count -ge 1) -and ((@(Test-ProbeRequest ([pscustomobject]@{ run_id = 'nep5-test-0004'; mode = 'connect'; timeout_ms = 3000; targets = @(1..13 | ForEach-Object { [pscustomobject]@{ family = 'v4'; port = 61763 } }) }))).Count -ge 1))
    Chk 'request: identity mode needs no targets' ((@(Test-ProbeRequest ([pscustomobject]@{ run_id = 'nep5-test-0005'; mode = 'identity'; timeout_ms = 3000 }))).Count -eq 0)
    $dReq = { param($d) [pscustomobject]@{ run_id = 'nep5-test-0006'; mode = 'direct'; timeout_ms = 3000; direct = $d } }
    Chk 'request: direct mode accepts exactly {op: add} and {op: delete}' (((@(Test-ProbeRequest (& $dReq ([pscustomobject]@{ op = 'add' })))).Count -eq 0) -and ((@(Test-ProbeRequest (& $dReq ([pscustomobject]@{ op = 'delete' })))).Count -eq 0))
    Chk 'request: direct mode refuses another op, a request that carries a SID, key or sublayer beside the op, a missing direct object and an upper-case op' (((@(Test-ProbeRequest (& $dReq ([pscustomobject]@{ op = 'uninstall' })))).Count -ge 1) -and ((@(Test-ProbeRequest (& $dReq ([pscustomobject]@{ op = 'add'; sid = 'S-1-5-21-1-2-3-1001' })))).Count -ge 1) -and ((@(Test-ProbeRequest (& $dReq ([pscustomobject]@{ op = 'delete'; key = 'f1763001-0000-4d8e-9a31-2b6d4c8e0099' })))).Count -ge 1) -and ((@(Test-ProbeRequest (& $dReq $null))).Count -ge 1) -and ((@(Test-ProbeRequest (& $dReq ([pscustomobject]@{ op = 'ADD' })))).Count -ge 1))
    Chk 'direct verdict: call + 0x0 succeeded; call + 0x5 or 0x80070005 denied; any other call status other; an open failure open_failed (an open says nothing about the write); compile / refused as named' (((Get-DirectVerdict 'call' '0x00000000') -eq 'succeeded') -and ((Get-DirectVerdict 'call' '0x00000005') -eq 'denied') -and ((Get-DirectVerdict 'call' '0x80070005') -eq 'denied') -and ((Get-DirectVerdict 'call' '0x80320007') -eq 'other') -and ((Get-DirectVerdict 'open' '0x00000005') -eq 'open_failed') -and ((Get-DirectVerdict 'compile' '') -eq 'compile_failed') -and ((Get-DirectVerdict 'refused' 'x') -eq 'refused'))
    Chk 'outcome: connected / blocked (10013) / refused (10061) / timeout / other error' (((Get-ConnectOutcome $true 0 $false) -eq 'connected') -and ((Get-ConnectOutcome $false 10013 $false) -eq 'blocked') -and ((Get-ConnectOutcome $false 10061 $false) -eq 'refused') -and ((Get-ConnectOutcome $false 10060 $false) -eq 'timeout') -and ((Get-ConnectOutcome $false 0 $true) -eq 'timeout') -and ((Get-ConnectOutcome $false 10051 $false) -eq 'error'))
    # the C# guards: compile in-process and ask the validators only. The engine-calling methods are never given a valid argument here.
    $compiled = $false; $compErr = ''
    try { Initialize-DirectType; $compiled = [bool]('BlarAI.Nep5Probe.Direct' -as [type]) } catch { $compErr = $_.Exception.Message }
    if (-not $compiled -and $PSVersionTable.PSEdition -eq 'Desktop' -and $compErr -match 'Access .* is denied') { Write-Host "  [SKIP] the direct C# was not compiled: Windows PowerShell 5.1 writes it to a DLL under %TEMP% and this machine's endpoint protection refused it ($compErr). Run the self-test under PowerShell 7." -ForegroundColor Yellow }
    else {
        Chk 'direct C#: compiles and exposes Add() and Delete()' ($compiled -and $null -ne ('BlarAI.Nep5Probe.Direct' -as [type]).GetMethod('Add') -and $null -ne ('BlarAI.Nep5Probe.Direct' -as [type]).GetMethod('Delete'))
        if ($compiled) {
            $D = [BlarAI.Nep5Probe.Direct]; $own = 'S-1-5-21-1000000001-1000000002-1000000003-1271'
            Chk 'direct C#: the constants are S2, our provider and the two fixed N1 keys' (($D::S2 -eq [guid]'3e29ae7e-fd9f-413a-8b8d-da9bd3a96359') -and ($D::Provider -eq [guid]'3e29ae7e-fd9f-413a-8b8d-da9bd3a96360') -and ($D::AddKey -eq [guid]'f1763001-0000-4d8e-9a31-2b6d4c8e0021') -and ($D::DeleteKey -eq [guid]'f1763001-0000-4d8e-9a31-2b6d4c8e0001'))
            Chk 'direct C#: the add is allowed only for the token''s own SID, in S2, with the fixed key (lock on)' (($null -eq $D::CheckAdd($own, $own, $D::S2, $D::AddKey)) -and ($null -ne $D::CheckAdd('S-1-5-21-1-2-3-1001', $own, $D::S2, $D::AddKey)) -and ($null -ne $D::CheckAdd('S-1-1-0', 'S-1-1-0', $D::S2, $D::AddKey)) -and ($null -ne $D::CheckAdd('', $own, $D::S2, $D::AddKey)) -and ($null -ne $D::CheckAdd($own, $own, [guid]'2c5d0ad6-5f3b-4d4e-9b8f-1a3e7c9d0b21', $D::AddKey)) -and ($null -ne $D::CheckAdd($own, $own, [guid]'c971a69f-d6ab-4885-9b49-506d8aa51c86', $D::AddKey)) -and ($null -ne $D::CheckAdd($own, $own, $D::S2, [guid]'f1763001-0000-4d8e-9a31-2b6d4c8e0001')))
            Chk 'direct C#: the delete is allowed only for S2 and the fixed test key; another key or sublayer is refused' (($null -eq $D::CheckDelete($D::S2, $D::DeleteKey)) -and ($null -ne $D::CheckDelete($D::S2, [guid]'f1763001-0000-4d8e-9a31-2b6d4c8e0099')) -and ($null -ne $D::CheckDelete([guid]'c971a69f-d6ab-4885-9b49-506d8aa51c86', $D::DeleteKey)))
            Chk 'direct C#: Add() for a SID that is not the running token''s own is refused before the engine is opened (phase refused; the operator running this self-test is not blarai-spike)' (([BlarAI.Nep5Probe.Direct]::Add($own))[0] -eq 'refused')
            if ([Environment]::Is64BitProcess) { Chk 'direct C#: x64 sizeof FILTER == 200 and COND == 40 (the layout the matrix''s own marshalling asserts)' (([Runtime.InteropServices.Marshal]::SizeOf([type]'BlarAI.Nep5Probe.FILTER') -eq 200) -and ([Runtime.InteropServices.Marshal]::SizeOf([type]'BlarAI.Nep5Probe.COND') -eq 40)) }
        }
    }
    # real loopback sockets: a listener of this process on an ephemeral port, then a closed port
    $l4 = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0); $l4.Start(); $p4 = ([Net.IPEndPoint]$l4.LocalEndpoint).Port
    $r4 = Invoke-ProbeConnect -Family v4 -Port $p4 -TimeoutMs 3000
    Chk 'connect (real loopback): a v4 listener of this process -> connected, code 0' (($r4.result -eq 'connected') -and ($r4.win32 -eq 0))
    $l4.Stop()
    $rc = Invoke-ProbeConnect -Family v4 -Port $p4 -TimeoutMs 3000
    Chk 'connect (real loopback): the same port once closed -> refused (10061), never "blocked"' (($rc.result -eq 'refused') -and ($rc.win32 -eq 10061))
    $l6 = $null; try { $l6 = New-Object Net.Sockets.TcpListener([Net.IPAddress]::IPv6Loopback, 0); $l6.Start() } catch { $l6 = $null }
    if ($l6) {
        $p6 = ([Net.IPEndPoint]$l6.LocalEndpoint).Port; $r6 = Invoke-ProbeConnect -Family v6 -Port $p6 -TimeoutMs 3000; $l6.Stop()
        Chk 'connect (real loopback): a [::1] listener of this process -> connected through the v6 path' (($r6.result -eq 'connected') -and ($r6.family -eq 'v6'))
    } else { Write-Host '  [SKIP] [::1] cannot bind on this machine: the v6 connect check is not run (a v6 row would be NOT RUN, never "blocked")' -ForegroundColor Yellow }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('nep5-probe-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $rp = Join-Path $tmp 'result-nep5-test-0001.json'; Write-ProbeResult -Path $rp -Object ([ordered]@{ schema_version = 1; run_id = 'nep5-test-0001'; rows = @($r4) })
        $back = Get-Content -LiteralPath $rp -Raw | ConvertFrom-Json
        Chk 'result file: written as UTF-8 without a BOM and parses back with the row intact' (([IO.File]::ReadAllBytes($rp)[0] -ne 0xEF) -and ($back.run_id -eq 'nep5-test-0001') -and (@($back.rows).Count -eq 1) -and (-not (Test-Path "$rp.tmp")))
    } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $self = Get-Content -LiteralPath $PSCommandPath -Raw
    Chk 'the probe calls no task API, no download and no network target other than the two loopback literals, and no WFP call other than the single add and the single delete' (($self -notmatch ('(?i)' + (@('Register-Scheduled' + 'Task', 'Start-Scheduled' + 'Task', 'Invoke-Web' + 'Request', '1[.]1[.]1[.]1', 'FwpmTransaction' + 'Begin', 'FwpmSubLayer' + 'Add', 'FwpmProvider' + 'Add', 'FwpmSubLayer' + 'DeleteByKey', 'FwpmProvider' + 'DeleteByKey', 'FwpmFilterCreate' + 'EnumHandle') -join '|'))) -and ([regex]::Matches($self, 'FwpmFilterAdd0\(h, ref f').Count -eq 1) -and ([regex]::Matches($self, 'FwpmFilterDeleteByKey0\(h, ref k').Count -eq 1))
    Write-Host ("nep5 probe selftest: {0}" -f $(if ($f -eq 0) { 'all passed' } else { "$f FAILED" }))
    exit $(if ($f -eq 0) { 0 } else { 1 })
}

# --- real run (as blarai-spike) -----------------------------------------------------------------------------------
$started = Get-Now
$cfg = Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json
$req = if ($RequestFile) { Get-Content -LiteralPath $RequestFile -Raw | ConvertFrom-Json } else { $null }
$rid = if ($req -and [string]$req.run_id -match '^[A-Za-z0-9-]{8,64}$') { [string]$req.run_id } else { 'invalid-' + (Get-Date -Format 'yyyyMMddHHmmssfff') }
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$result = [ordered]@{ schema_version = 1; kind = 'nep5-probe'; run_id = $rid; mode = $(if ($req) { [string]$req.mode } else { '' }); started = $started; finished = $null; token_sid = $id.User.Value; token_name = $id.Name
                      expected_sid = [string]$cfg.expected_sid; targets = @(); direct = $null; error = $null; overall = 'error' }
try {
    $problems = @(Test-ProbeRequest $req)
    if ($problems.Count) { throw ("request refused: " + ($problems -join '; ')) }
    if ($req.mode -eq 'connect') { foreach ($t in @($req.targets)) { $result.targets += , (Invoke-ProbeConnect -Family ([string]$t.family) -Port ([int]$t.port) -TimeoutMs ([int]$req.timeout_ms)) } }
    if ($req.mode -eq 'direct') { $result.direct = Invoke-DirectCall -Op ([string]$req.direct.op) -OwnSid ([string]$cfg.expected_sid) }
    $result.overall = 'done'
} catch { $result.error = $_.Exception.Message }
$result.finished = Get-Now
Write-ProbeResult -Path (Join-Path ([string]$cfg.results_dir) "result-$rid.json") -Object $result
exit $(if ($result.overall -eq 'done') { 0 } else { 1 })
