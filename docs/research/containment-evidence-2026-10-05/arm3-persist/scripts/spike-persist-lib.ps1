#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3 library (persistent WFP filter set): everything that adds, checks, exports and REMOVES the persistent objects, and
  the gate that keeps the add path unreachable until the rollback has been self-tested. Dot-source it; it has no side
  effects on load (the C# is compiled only by Initialize-PersistType) and calls no WFP API until a backend is created.

.DESCRIPTION
  Backend seam. Every WFP action goes through a "backend" object with four methods: Flags(kind, key) (-1 when absent),
  AddAll(plan), Delete(kind, key) (deleted | not_found | error: ...) and Close(). New-RealBackend wraps the C# engine (a NON-dynamic session); New-FakeBackend
  is an in-memory store with switchable failures. -SelfTest drives all of the logic below against the fake, including a
  half-failed add and a failing delete, so the rollback is proved before any real backend can be created for an add.

  Objects (fixed keys, never generated): one provider, one sublayer, two BLOCK filters (ALE_AUTH_CONNECT V4 and V6), all
  with the persistent flag, every filter carrying the ALE_USER_ID condition for the spike account's SID. The keys differ
  from the dynamic spike's (arms 1 and 2), so a run of those cannot be confused with this set.

  States (Get-FenceState): ABSENT (none of the four objects), PRESENT (all four), PARTIAL (some), UNKNOWN (the engine could
  not be queried: BFE down, not elevated, an unexpected status). Test-FenceAllowsAccount allows the account to run ONLY for
  PRESENT; every other state, including UNKNOWN, refuses. PRESENT here means the four keys exist: the filter CONDITIONS are
  not read back, so a key reused with different content would pass (see DESIGN.md, limits).
#>

# ---- constants -----------------------------------------------------------------------------------------------------
$script:PersistMarker = 'BlarAI #1682'
$script:PersistProviderKey = '7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f01'
$script:PersistSubLayerKey = '7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02'
$script:PersistFilterKeys  = @('f1300003-0000-4d8e-9a31-2b6d4c8e3f21', 'f1300004-0000-4d8e-9a31-2b6d4c8e3f22')
# Deletion order matters: a sublayer must be empty before it is deleted and the provider must own nothing.
$script:PersistObjects = @(
    [pscustomobject]@{ Kind = 'filter';   Key = $script:PersistFilterKeys[0];  Name = 'block-account-v4' }
    [pscustomobject]@{ Kind = 'filter';   Key = $script:PersistFilterKeys[1];  Name = 'block-account-v6' }
    [pscustomobject]@{ Kind = 'sublayer'; Key = $script:PersistSubLayerKey;    Name = 'sublayer' }
    [pscustomobject]@{ Kind = 'provider'; Key = $script:PersistProviderKey;    Name = 'provider' }
)
$script:RequiredRollbackTags = @('remove-full-set', 'remove-half-failed-add', 'remove-when-absent', 'remove-reports-delete-error', 'remove-continues-after-error',
                                 'absent-detected', 'partial-detected', 'unknown-detected', 'guard-refuses-unless-present', 'add-refused-without-proof',
                                 'add-refused-over-stale-objects', 'add-failure-rolls-back', 'proof-hash-binding')
# Files whose bytes the rollback proof binds (the scripts of arm 3 that can add, remove or gate). All live in one folder.
$script:CodeSetFiles = @('spike-lib.ps1', 'spike-task-driver.ps1', 'spike-persist-lib.ps1', 'spike-wfp-persist.ps1', 'spike-arm3b-common.ps1', 'spike-arm3b-arm.ps1', 'spike-arm3b-post-reboot.ps1', 'spike-arm3b-veto.ps1', 'arm3-idle-gate.ps1', 'Start-ElevatedOnce.ps1')
$script:ProofMaxAgeHours = 24
$script:MinSelfTestChecks = 60

# ---- the C# (appended to the wrapped #1671 source so it can reuse its structs and Native imports) -----------------------
$script:PersistCSharp = @'

namespace BlarAI.WfpPersist
{
    using System;
    using System.Collections.Generic;
    using System.Runtime.InteropServices;
    using System.Security.AccessControl;
    using System.Text;
    using BlarAI.Wfp;

    public static class PNative
    {
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmFilterDeleteByKey0(IntPtr engineHandle, ref Guid key);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmSubLayerDeleteByKey0(IntPtr engineHandle, ref Guid key);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmProviderDeleteByKey0(IntPtr engineHandle, ref Guid key);
    }

    public static class PersistKeys
    {
        // Our own keys (generated for this spike; not Microsoft values). Fixed on purpose: removal is by these keys.
        public static readonly Guid Provider = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f01");
        public static readonly Guid SubLayer = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02");
        public static readonly Guid FilterV4 = new Guid("f1300003-0000-4d8e-9a31-2b6d4c8e3f21");
        public static readonly Guid FilterV6 = new Guid("f1300004-0000-4d8e-9a31-2b6d4c8e3f22");
        // fwpmtypes.h: FWPM_PROVIDER_FLAG_PERSISTENT, FWPM_SUBLAYER_FLAG_PERSISTENT, FWPM_FILTER_FLAG_PERSISTENT are all 0x00000001.
        public const uint Persistent = 1;
        public const string Marker = "BlarAI #1682";
        // winerror.h: FWP_E_FILTER_NOT_FOUND, FWP_E_PROVIDER_NOT_FOUND, FWP_E_SUBLAYER_NOT_FOUND, FWP_E_NOT_FOUND.
        public const uint NotFoundFilter = 0x80320003, NotFoundProvider = 0x80320005, NotFoundSubLayer = 0x80320007, NotFoundGeneric = 0x80320008;
    }

    public sealed class PersistPlan
    {
        public string Sid; public byte[] Sd; public string Sddl; public List<FilterSpec> Filters = new List<FilterSpec>();

        public static PersistPlan Build(string sid)
        {
            if (!Plan.IsAcceptableCoderSid(sid)) throw new ArgumentException("refusing SID (not an account-domain user SID): " + sid);
            PersistPlan p = new PersistPlan(); p.Sid = sid; p.Sd = Plan.BuildSd(sid);
            p.Sddl = new RawSecurityDescriptor(p.Sd, 0).GetSddlForm(AccessControlSections.Access);
            p.Filters.Add(Mk(PersistKeys.FilterV4, "block-account-v4", "ALE_AUTH_CONNECT_V4", Plan.LayerConnectV4));
            p.Filters.Add(Mk(PersistKeys.FilterV6, "block-account-v6", "ALE_AUTH_CONNECT_V6", Plan.LayerConnectV6));
            return p;
        }

        static FilterSpec Mk(Guid key, string name, string layerName, Guid layer)
        {
            FilterSpec f = new FilterSpec(); f.Key = key; f.Name = PersistKeys.Marker + " persist spike: " + name; f.LayerName = layerName;
            f.Layer = layer; f.Action = Plan.FWP_ACTION_BLOCK; f.Weight = Plan.BlockWeight; f.Loopback = false; return f;
        }

        public string Describe()
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("account SID    : " + Sid);
            sb.AppendLine("SD (SDDL)      : " + Sddl);
            sb.AppendLine("session        : NON-dynamic (FWPM_SESSION0.flags = 0): the objects outlive this process and survive a reboot");
            sb.AppendLine("provider       : " + PersistKeys.Provider + "  flags=0x1 (FWPM_PROVIDER_FLAG_PERSISTENT)");
            sb.AppendLine("sublayer       : " + PersistKeys.SubLayer + "  flags=0x1 (FWPM_SUBLAYER_FLAG_PERSISTENT)  weight=0x" + Plan.SubLayerWeight.ToString("X") + "  provider=" + PersistKeys.Provider);
            foreach (FilterSpec f in Filters)
            {
                sb.AppendLine("filter " + f.Key + "  " + f.Name + "  flags=0x1 (FWPM_FILTER_FLAG_PERSISTENT)");
                sb.AppendLine("   layer " + f.LayerName + " " + f.Layer + "  action=BLOCK(0x1001)  weight=FWP_UINT64 0x" + f.Weight.ToString("X") + "  sublayer=" + PersistKeys.SubLayer);
                sb.AppendLine("   cond  FWPM_CONDITION_ALE_USER_ID " + Plan.CondAleUserId + "  FWP_MATCH_EQUAL  FWP_SECURITY_DESCRIPTOR_TYPE(14) -> SD above");
            }
            return sb.ToString();
        }
    }

    // All unmanaged memory for one PersistPlan (BFE copies everything during Add, so Free() after the transaction is safe).
    public sealed class PersistMarshal
    {
        public List<IntPtr> Allocs = new List<IntPtr>();
        public FWPM_PROVIDER0 Provider; public FWPM_SUBLAYER0 SubLayer; public List<FWPM_FILTER0> Filters = new List<FWPM_FILTER0>();
        public List<byte[]> FilterImages = new List<byte[]>(); public byte[] ProviderImage, SubLayerImage;

        IntPtr A(int n) { IntPtr p = Marshal.AllocHGlobal(n); Allocs.Add(p); return p; }
        IntPtr Str(string s) { IntPtr p = Marshal.StringToHGlobalUni(s); Allocs.Add(p); return p; }
        IntPtr GuidPtr(Guid g) { IntPtr p = A(16); Marshal.StructureToPtr(g, p, false); return p; }
        IntPtr U64(ulong v) { IntPtr p = A(8); Marshal.WriteInt64(p, unchecked((long)v)); return p; }
        FWPM_DISPLAY_DATA0 DD(string n, string d) { FWPM_DISPLAY_DATA0 x = new FWPM_DISPLAY_DATA0(); x.name = Str(n); x.description = Str(d); return x; }
        IntPtr Blob(byte[] data)
        {
            IntPtr d = A(data.Length); Marshal.Copy(data, 0, d, data.Length);
            FWP_BYTE_BLOB b = new FWP_BYTE_BLOB(); b.size = (uint)data.Length; b.data = d;
            IntPtr bp = A(Marshal.SizeOf(typeof(FWP_BYTE_BLOB))); Marshal.StructureToPtr(b, bp, false); return bp;
        }
        public static byte[] Image<T>(T s)
        {
            int n = Marshal.SizeOf(typeof(T)); IntPtr p = Marshal.AllocHGlobal(n);
            try { Marshal.StructureToPtr(s, p, false); byte[] b = new byte[n]; Marshal.Copy(p, b, 0, n); return b; }
            finally { Marshal.FreeHGlobal(p); }
        }

        public static PersistMarshal Build(PersistPlan plan)
        {
            PersistMarshal m = new PersistMarshal();
            IntPtr provKeyPtr = m.GuidPtr(PersistKeys.Provider);
            m.Provider = new FWPM_PROVIDER0(); m.Provider.providerKey = PersistKeys.Provider; m.Provider.flags = PersistKeys.Persistent;
            m.Provider.displayData = m.DD(PersistKeys.Marker + " persist spike provider", "Persistent provider for the persistence spike; removed by key (spike-wfp-persist.ps1 -Remove).");
            m.ProviderImage = Image(m.Provider);
            m.SubLayer = new FWPM_SUBLAYER0(); m.SubLayer.subLayerKey = PersistKeys.SubLayer; m.SubLayer.providerKey = provKeyPtr; m.SubLayer.flags = PersistKeys.Persistent;
            m.SubLayer.displayData = m.DD(PersistKeys.Marker + " persist spike sublayer", "Persistent sublayer for the persistence spike; removed by key.");
            m.SubLayer.weight = Plan.SubLayerWeight; m.SubLayerImage = Image(m.SubLayer);

            IntPtr sdBlob = m.Blob(plan.Sd);
            int condSize = Marshal.SizeOf(typeof(FWPM_FILTER_CONDITION0));
            foreach (FilterSpec f in plan.Filters)
            {
                FWPM_FILTER_CONDITION0 u = new FWPM_FILTER_CONDITION0(); u.fieldKey = Plan.CondAleUserId; u.matchType = Plan.FWP_MATCH_EQUAL;
                u.conditionValue.type = Plan.FWP_SECURITY_DESCRIPTOR_TYPE; u.conditionValue.value = sdBlob;
                IntPtr arr = m.A(condSize); Marshal.StructureToPtr(u, arr, false);
                FWPM_FILTER0 fl = new FWPM_FILTER0(); fl.filterKey = f.Key; fl.displayData = m.DD(f.Name, "Persistent filter, keyed to the spike account's SID.");
                fl.flags = PersistKeys.Persistent; fl.providerKey = provKeyPtr; fl.layerKey = f.Layer; fl.subLayerKey = PersistKeys.SubLayer;
                fl.weight.type = Plan.FWP_UINT64; fl.weight.value = m.U64(f.Weight);
                fl.numFilterConditions = 1; fl.filterCondition = arr; fl.action.type = f.Action;
                m.Filters.Add(fl); m.FilterImages.Add(Image(fl));
            }
            return m;
        }

        public void Free() { foreach (IntPtr p in Allocs) Marshal.FreeHGlobal(p); Allocs.Clear(); }
    }

    // A NON-dynamic engine session: what it adds persists. Every method that reads or deletes treats "not found" as a normal answer.
    public sealed class PersistEngine
    {
        IntPtr handle; readonly object gate = new object();
        public bool IsOpen { get { lock (gate) { return handle != IntPtr.Zero; } } }

        public static PersistEngine Open(string name)
        {
            FWPM_SESSION0 s = new FWPM_SESSION0();
            IntPtr nm = Marshal.StringToHGlobalUni(name);
            try
            {
                s.displayData.name = nm; s.flags = 0; s.txnWaitTimeoutInMSec = 10000;
                IntPtr h;
                uint rc = Native.FwpmEngineOpen0(null, 0xFFFFFFFF, IntPtr.Zero, ref s, out h);
                if (rc != 0) throw new InvalidOperationException("FwpmEngineOpen0 failed 0x" + rc.ToString("X8"));
                PersistEngine e = new PersistEngine(); e.handle = h; return e;
            }
            finally { Marshal.FreeHGlobal(nm); }
        }

        public void Close() { lock (gate) { if (handle == IntPtr.Zero) return; Native.FwpmEngineClose0(handle); handle = IntPtr.Zero; } }

        static void Check(string what, uint rc) { if (rc != 0) throw new InvalidOperationException(what + " failed 0x" + rc.ToString("X8")); }

        public ulong[] AddAll(PersistPlan plan)
        {
            PersistMarshal m = PersistMarshal.Build(plan); bool inTxn = false; List<ulong> ids = new List<ulong>();
            try
            {
                lock (gate)
                {
                    if (handle == IntPtr.Zero) throw new InvalidOperationException("engine closed");
                    Check("FwpmTransactionBegin0", Native.FwpmTransactionBegin0(handle, 0)); inTxn = true;
                    FWPM_PROVIDER0 p = m.Provider; Check("FwpmProviderAdd0", Native.FwpmProviderAdd0(handle, ref p, IntPtr.Zero));
                    FWPM_SUBLAYER0 sl = m.SubLayer; Check("FwpmSubLayerAdd0", Native.FwpmSubLayerAdd0(handle, ref sl, IntPtr.Zero));
                    foreach (FWPM_FILTER0 f0 in m.Filters)
                    {
                        FWPM_FILTER0 f = f0; ulong id;
                        Check("FwpmFilterAdd0", Native.FwpmFilterAdd0(handle, ref f, IntPtr.Zero, out id)); ids.Add(id);
                    }
                    Check("FwpmTransactionCommit0", Native.FwpmTransactionCommit0(handle)); inTxn = false;
                }
            }
            catch { if (inTxn) { lock (gate) { if (handle != IntPtr.Zero) Native.FwpmTransactionAbort0(handle); } } throw; }
            finally { m.Free(); }
            return ids.ToArray();
        }

        static uint NotFoundFor(string kind)
        {
            if (kind == "filter") return PersistKeys.NotFoundFilter;
            if (kind == "provider") return PersistKeys.NotFoundProvider;
            if (kind == "sublayer") return PersistKeys.NotFoundSubLayer;
            throw new ArgumentException("kind must be provider, sublayer or filter: " + kind);
        }

        // -1 = not found; otherwise the object's flags. Anything other than found / not found throws (callers treat that as UNKNOWN).
        public long Flags(string kind, Guid key)
        {
            uint nf = NotFoundFor(kind); IntPtr o; uint rc;
            lock (gate)
            {
                if (handle == IntPtr.Zero) throw new InvalidOperationException("engine closed");
                if (kind == "filter") rc = Native.FwpmFilterGetByKey0(handle, ref key, out o);
                else if (kind == "provider") rc = Native.FwpmProviderGetByKey0(handle, ref key, out o);
                else rc = Native.FwpmSubLayerGetByKey0(handle, ref key, out o);
            }
            if (rc == nf || rc == PersistKeys.NotFoundGeneric) return -1;
            if (rc != 0) throw new InvalidOperationException(kind + " lookup failed 0x" + rc.ToString("X8"));
            try
            {
                if (kind == "filter") return ((FWPM_FILTER0)Marshal.PtrToStructure(o, typeof(FWPM_FILTER0))).flags;
                if (kind == "provider") return ((FWPM_PROVIDER0)Marshal.PtrToStructure(o, typeof(FWPM_PROVIDER0))).flags;
                return ((FWPM_SUBLAYER0)Marshal.PtrToStructure(o, typeof(FWPM_SUBLAYER0))).flags;
            }
            finally { Native.FwpmFreeMemory0(ref o); }
        }

        // Deletes ONE object by key, outside any transaction (so a failure on one never undoes the others). Returns the raw status.
        public uint Delete(string kind, Guid key)
        {
            NotFoundFor(kind);
            lock (gate)
            {
                if (handle == IntPtr.Zero) throw new InvalidOperationException("engine closed");
                if (kind == "filter") return PNative.FwpmFilterDeleteByKey0(handle, ref key);
                if (kind == "provider") return PNative.FwpmProviderDeleteByKey0(handle, ref key);
                return PNative.FwpmSubLayerDeleteByKey0(handle, ref key);
            }
        }
    }
}
'@

# A self-contained removal that depends on nothing else in this folder: the manual rollback (printed by -DryRun, in the README, and
# compiled - never run - by -SelfTest under a different type name). Deletes filters, then the sublayer, then the provider, by key.
$script:ManualRollbackSnippet = @'
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class ManualWfpRollback {
  [StructLayout(LayoutKind.Sequential)] struct NAME { public IntPtr n; public IntPtr d; }
  [StructLayout(LayoutKind.Sequential)] struct SESSION { public Guid k; public NAME dd; public uint flags; public uint txn; public uint pid; public IntPtr sid; public IntPtr user; public int kernel; }
  [DllImport("fwpuclnt.dll", CharSet = CharSet.Unicode)] static extern uint FwpmEngineOpen0(string s, uint a, IntPtr i, ref SESSION se, out IntPtr h);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmEngineClose0(IntPtr h);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmFilterDeleteByKey0(IntPtr h, ref Guid k);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmSubLayerDeleteByKey0(IntPtr h, ref Guid k);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmProviderDeleteByKey0(IntPtr h, ref Guid k);
  public static string Run() {
    SESSION se = new SESSION(); IntPtr h; uint rc = FwpmEngineOpen0(null, 0xFFFFFFFF, IntPtr.Zero, ref se, out h);
    if (rc != 0) return "engine open failed 0x" + rc.ToString("X8");
    string r = "";
    foreach (string f in new string[] { "f1300003-0000-4d8e-9a31-2b6d4c8e3f21", "f1300004-0000-4d8e-9a31-2b6d4c8e3f22" }) { Guid g = new Guid(f); r += "filter " + f + " 0x" + FwpmFilterDeleteByKey0(h, ref g).ToString("X8") + "\n"; }
    Guid s2 = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02"); r += "sublayer 0x" + FwpmSubLayerDeleteByKey0(h, ref s2).ToString("X8") + "\n";
    Guid p2 = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f01"); r += "provider 0x" + FwpmProviderDeleteByKey0(h, ref p2).ToString("X8") + "\n";
    FwpmEngineClose0(h); return r;
  }
}
"@
[ManualWfpRollback]::Run()   # 0x00000000 = deleted; 0x80320003/05/07 = was already gone. Then: netsh wfp show filters file=check.xml  and search it for "BlarAI #1682".
'@

# ---- wrapped-script helpers (the same extraction spike-wfp.ps1 uses) -----------------------------------------------------------
$script:WrappedFunctions = @('Test-CoderSidSafe', 'Test-TcpConnect', 'Test-IsElevated', 'Get-OperatorTokenSids', 'Get-EnvSnapshot')

function Import-WfpHelpers {
    # Reads (never runs or edits) the validated #1671 script: its embedded C# into $script:csharp and a handful of helper
    # functions into script scope, with the PowerShell parser. Throws if anything is missing. With -ExpectedSha256 (LF-normalised, as
    # Get-NormalizedSha256) the file must match BEFORE any of its text is parsed or evaluated: the SYSTEM tasks pin the hash taken
    # at arming, because the text of this file becomes code in a privileged process.
    param([Parameter(Mandatory)][string]$Path, [string]$ExpectedSha256, [switch]$Unverified)
    if (-not (Test-Path -LiteralPath $Path)) { throw "wrapped script not found: $Path" }
    # GATE, before a byte is read as code: the text of this file becomes code in the calling (often elevated) process, so it must be either pinned by hash (-ExpectedSha256) or
    # sit in an admin-only folder that nobody else can write to. -Unverified is for -SelfTest only, which runs the repository copy of the validated script by design.
    if (-not $ExpectedSha256 -and -not $Unverified) {
        $ao = Test-AdminOnlyFolder -Path (Split-Path (Resolve-Path -LiteralPath $Path).Path -Parent)
        if (-not $ao.Ok) { throw ("the wrapped script '$Path' is neither pinned by hash (-WfpSha256) nor in an admin-only folder, so its text will not be evaluated: " + (@($ao.Problems | Select-Object -First 2) -join '; ')) }
    }
    # ONE read: the bytes that are hashed are the bytes that are parsed and evaluated (a second read of the path would be a time-of-check/time-of-use gap).
    $bytes = [IO.File]::ReadAllBytes($Path)
    $hash = Get-NormalizedSha256FromBytes -Bytes $bytes
    if ($ExpectedSha256 -and $hash -ne $ExpectedSha256.ToUpperInvariant()) { throw "wrapped script hash $hash is not the pinned $($ExpectedSha256.ToUpperInvariant()): refusing to turn its text into code" }
    $tokens = $null; $errs = $null
    $ast = [Management.Automation.Language.Parser]::ParseInput([Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF), [ref]$tokens, [ref]$errs)
    if ($errs -and $errs.Count) { throw "wrapped script does not parse: $($errs[0].Message)" }
    $assign = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$csharp' }, $true) | Select-Object -First 1
    if (-not $assign) { throw 'wrapped script has no $csharp assignment' }
    $script:csharp = & ([scriptblock]::Create($assign.Right.Extent.Text))
    if (-not ($script:csharp -is [string]) -or $script:csharp -notmatch 'namespace BlarAI\.Wfp') { throw 'extracted $csharp is not the WFP type source' }
    $found = @()
    foreach ($name in $script:WrappedFunctions) {
        $fn = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true) | Select-Object -First 1
        if (-not $fn) { throw "wrapped script has no function $name" }
        Set-Item -Path ("Function:script:$name") -Value $fn.Body.GetScriptBlock()
        $found += $name
    }
    $script:WrappedSha256Used = $hash   # the hash of the bytes this call evaluated: what a rollback proof must be compared with
    return [pscustomobject]@{ Path = $Path; Sha256 = $hash; Functions = $found; CsharpChars = $script:csharp.Length }
}

function Initialize-PersistType {
    # Compiles the wrapped source and this library's namespace as ONE unit (so the persist types can use the wrapped structs).
    if (-not $script:csharp) { throw 'Import-WfpHelpers must run first' }
    if (-not ('BlarAI.WfpPersist.PersistEngine' -as [type])) {
        if ('BlarAI.Wfp.Plan' -as [type]) { throw 'BlarAI.Wfp is already loaded without the persist types in this session: start a fresh PowerShell' }
        Add-Type -TypeDefinition ($script:csharp + $script:PersistCSharp) -Language CSharp
    }
}

# ---- hashing and the rollback proof ---------------------------------------------------------------------------------------
function Get-NormalizedSha256FromBytes {
    # SHA-256 of the bytes with CRLF read as LF, so a CRLF checkout and an LF checkout of the same text agree.
    param([Parameter(Mandatory)][byte[]]$Bytes)
    $ms = New-Object IO.MemoryStream
    for ($i = 0; $i -lt $Bytes.Length; $i++) { if ($Bytes[$i] -eq 13 -and $i + 1 -lt $Bytes.Length -and $Bytes[$i + 1] -eq 10) { continue }; $ms.WriteByte($Bytes[$i]) }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($ms.ToArray()))) -replace '-', '' } finally { $sha.Dispose(); $ms.Dispose() }
}

function Get-NormalizedSha256 {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-NormalizedSha256FromBytes -Bytes ([IO.File]::ReadAllBytes($Path)))
}

function Get-CodeSetHashes {
    # name -> hash for every file of the code set that exists in $Folder; a missing file is reported by name, never skipped.
    param([Parameter(Mandatory)][string]$Folder)
    $h = [ordered]@{}; $missing = @()
    foreach ($n in $script:CodeSetFiles) {
        $p = Join-Path $Folder $n
        # A library this process loaded through Get-VerifiedLibBlock is represented by the hash of the bytes it actually ran, not by a fresh read of the path.
        if ($script:LoadedLibHashes -and $script:LoadedLibHashes.ContainsKey($n) -and $script:LoadedLibFolder -and ($script:LoadedLibFolder.TrimEnd('\', '/') -eq $Folder.TrimEnd('\', '/'))) { $h[$n] = $script:LoadedLibHashes[$n] }
        elseif (Test-Path -LiteralPath $p) { $h[$n] = Get-NormalizedSha256 -Path $p } else { $missing += $n }
    }
    return [pscustomobject]@{ Hashes = $h; Missing = $missing }
}

function New-RollbackProofObject {
    # PURE on its arguments. The record -SelfTest -WriteProof saves: the hashes it ran against and the rollback tags that passed.
    param($Hashes, [string[]]$PassedTags, [string[]]$FailedChecks, [string]$HostInfo, [string]$When, [string]$WrappedHash = '', [int]$ChecksRun = 0, [int]$ChecksPassed = 0, $Siblings = @())
    $allTags = @($script:RequiredRollbackTags | Where-Object { $PassedTags -contains $_ })
    return [ordered]@{
        schema = 2; kind = 'rollback-selftest-proof'; written = $When; host = $HostInfo; sha256_lf_normalised = $Hashes
        wrapped_script_sha256 = $WrappedHash
        selftest = [ordered]@{ checks_run = $ChecksRun; checks_passed = $ChecksPassed }
        sibling_selftests = @($Siblings)
        rollback_tags_passed = @($PassedTags | Select-Object -Unique); rollback_tags_required = @($script:RequiredRollbackTags)
        rollback_checks_passed = ($allTags.Count -eq $script:RequiredRollbackTags.Count -and @($FailedChecks).Count -eq 0)
        failed_checks = @($FailedChecks); passed = (@($FailedChecks).Count -eq 0 -and $allTags.Count -eq $script:RequiredRollbackTags.Count)
    }
}

function Get-ChecksCeiling {
    # The most checks a real -SelfTest of the persist script can run: its check call sites plus slack for the sibling loop. 0 when the script is absent.
    param([Parameter(Mandatory)][string]$Folder)
    $p = Join-Path $Folder 'spike-wfp-persist.ps1'
    if (-not (Test-Path -LiteralPath $p)) { return 0 }
    return (@([IO.File]::ReadAllLines($p) | Where-Object { $_ -match '^\s*Chk [''"]' }).Count + 10)
}

function Test-RollbackProof {
    # Returns @{ Kind = 'RollbackProof'; Ok; Problems[] ... }. Ok only when the file exists, parses, says passed, lists every required
    # rollback tag, is younger than the age limit, and its recorded hash of EVERY code-set file equals the file's hash now.
    # This object is the token Add-FenceSet demands: there is no other way to build one.
    # It also binds the wrapped #1671 script (the code that builds the security descriptor): its hash now must equal the one recorded, and the
    # proof must carry the evidence a real run leaves (at least MinSelfTestChecks checks run and all passed, every sibling self-test passed).
    param([Parameter(Mandatory)][string]$ProofPath, [Parameter(Mandatory)][string]$Folder, [string]$WrappedSha256, [datetimeoffset]$Now = [datetimeoffset]::Now, [int]$MaxAgeHours = $script:ProofMaxAgeHours)
    $problems = New-Object System.Collections.ArrayList
    $tok = [pscustomobject]@{ Kind = 'RollbackProof'; Ok = $false; Problems = @(); ProofPath = $ProofPath; Written = $null }
    if (-not (Test-Path -LiteralPath $ProofPath)) { [void]$problems.Add("no rollback self-test proof at ${ProofPath}: run spike-wfp-persist.ps1 -SelfTest -WriteProof first"); $tok.Problems = @($problems); return $tok }
    $p = $null
    try { $p = ConvertFrom-Json ([IO.File]::ReadAllText($ProofPath)) } catch { [void]$problems.Add("proof file does not parse: $($_.Exception.Message)"); $tok.Problems = @($problems); return $tok }
    if ($p.kind -ne 'rollback-selftest-proof') { [void]$problems.Add('proof file is not a rollback-selftest-proof') }
    if (-not $p.passed -or -not $p.rollback_checks_passed) { [void]$problems.Add('the recorded self-test did not pass') }
    if ($p.schema -ne 2) { [void]$problems.Add("proof schema $($p.schema) is not 2: re-run the self-test with these scripts") }
    if (-not $p.selftest -or [int]$p.selftest.checks_run -lt $script:MinSelfTestChecks -or [int]$p.selftest.checks_passed -ne [int]$p.selftest.checks_run) { [void]$problems.Add("the proof does not record a self-test run (at least $($script:MinSelfTestChecks) checks, all passed)") }
    $sib = @($p.sibling_selftests)
    if ($sib.Count -lt 4 -or @($sib | Where-Object { -not $_.passed -or [int]$_.checks -lt 5 }).Count) { [void]$problems.Add('the proof does not record every sibling script''s self-test as passed') }
    if (-not $WrappedSha256) { [void]$problems.Add('no hash of the wrapped #1671 script was supplied (it must be the hash of the bytes Import-WfpHelpers evaluated)') }
    else {
        $wnow = $WrappedSha256.ToUpperInvariant()
        if (-not $p.wrapped_script_sha256) { [void]$problems.Add('the proof has no hash of the wrapped #1671 script') }
        elseif ([string]$p.wrapped_script_sha256 -ne $wnow) { [void]$problems.Add("the wrapped #1671 script changed since the self-test (proof $(([string]$p.wrapped_script_sha256).Substring(0, 12))..., now $($wnow.Substring(0, 12))...)") }
    }
    if (@($p.failed_checks).Count) { [void]$problems.Add("the proof records failed checks: $((@($p.failed_checks) | Select-Object -First 3) -join '; ')") }
    $ceil = Get-ChecksCeiling -Folder $Folder
    if ($ceil -le 0) { [void]$problems.Add('cannot judge whether the recorded number of checks is plausible: the persist script is not in the folder') }
    elseif ($p.selftest -and [int]$p.selftest.checks_run -gt $ceil) { [void]$problems.Add("the proof claims $([int]$p.selftest.checks_run) checks run but the self-test has at most $ceil check sites: not a real run") }
    $tags = @($p.rollback_tags_passed)
    foreach ($t in $script:RequiredRollbackTags) { if ($tags -notcontains $t) { [void]$problems.Add("rollback check '$t' is not in the proof") } }
    try {
        $w = ConvertTo-DateTimeOffset $p.written; $tok.Written = $w
        $age = ($Now - $w).TotalHours
        if ($age -gt $MaxAgeHours) { [void]$problems.Add(("proof is {0:N1} h old (limit {1} h): re-run the self-test" -f $age, $MaxAgeHours)) }
        if ($age -lt -0.1) { [void]$problems.Add('proof is dated in the future') }
    } catch { [void]$problems.Add("proof timestamp unreadable: $($_.Exception.Message)") }
    $cur = Get-CodeSetHashes -Folder $Folder
    foreach ($m in $cur.Missing) { [void]$problems.Add("code-set file missing from ${Folder}: $m") }
    $rec = $p.sha256_lf_normalised
    foreach ($n in $cur.Hashes.Keys) {
        $was = if ($rec) { [string]$rec.$n } else { '' }
        if (-not $was) { [void]$problems.Add("proof has no hash for $n") }
        elseif ($was -ne $cur.Hashes[$n]) { [void]$problems.Add("$n changed since the self-test (proof $($was.Substring(0, 12))..., now $($cur.Hashes[$n].Substring(0, 12))...): re-run the self-test") }
    }
    $tok.Problems = @($problems); $tok.Ok = ($problems.Count -eq 0)
    return $tok
}

# ---- fence state, guard, add, remove (all against a backend) --------------------------------------------------------------
function Get-FenceState {
    # ABSENT | PRESENT | PARTIAL | UNKNOWN. Never throws: a backend that cannot answer is UNKNOWN, which refuses like ABSENT.
    param([Parameter(Mandatory)]$Backend)
    $present = @(); $missing = @(); $flags = [ordered]@{}; $nonPersistent = 0
    try {
        foreach ($o in $script:PersistObjects) {
            $f = [long]$Backend.Flags($o.Kind, $o.Key)
            if ($f -lt 0) { $missing += "$($o.Kind):$($o.Name)" }
            else { $present += "$($o.Kind):$($o.Name)"; $flags["$($o.Kind):$($o.Name)"] = ('0x{0:X}' -f $f); if (($f -band 1) -eq 0) { $nonPersistent++ } }
        }
    } catch {
        return [ordered]@{ State = 'UNKNOWN'; Present = @($present); Missing = @($missing); AllPersistent = $false; Flags = $flags; Error = $_.Exception.Message }
    }
    $state = if ($present.Count -eq 0) { 'ABSENT' } elseif ($missing.Count -eq 0) { 'PRESENT' } else { 'PARTIAL' }
    $allPersistent = ($present.Count -gt 0 -and $nonPersistent -eq 0)
    return [ordered]@{ State = $state; Present = $present; Missing = $missing; AllPersistent = $allPersistent; Flags = $flags; Error = $null }
}

function Test-FenceAllowsAccount {
    # The fail-closed gate in front of every start of the account's task: allowed ONLY when all four objects are present.
    param([Parameter(Mandatory)]$Backend)
    $s = Get-FenceState -Backend $Backend
    if ($s.State -eq 'PRESENT') { return [ordered]@{ Allowed = $true; State = 'PRESENT'; Reason = 'fence present: all four objects exist'; Detail = $s } }
    $why = switch ($s.State) {
        'ABSENT'  { 'fence ABSENT: the account is not allowed to run' }
        'PARTIAL' { "fence PARTIAL (missing: $($s.Missing -join ', ')): the account is not allowed to run" }
        default   { "fence state UNKNOWN ($($s.Error)): the account is not allowed to run" }
    }
    return [ordered]@{ Allowed = $false; State = $s.State; Reason = $why; Detail = $s }
}

function Remove-FenceSet {
    # Removal BY KEY, built for a set that is whole, half-added, or already gone. Every key is attempted whatever happened to the
    # one before; "not found" is success; any other failing status is recorded and makes Ok false. The verdict is the state read
    # back afterwards: Ok only when it is ABSENT.
    param([Parameter(Mandatory)]$Backend)
    $rows = @()
    foreach ($o in $script:PersistObjects) {
        $st = 'error: not attempted'
        try { $st = [string]$Backend.Delete($o.Kind, $o.Key) } catch { $st = "error: $($_.Exception.Message)" }
        $rows += [ordered]@{ kind = $o.Kind; key = $o.Key; name = $o.Name; status = $st }
    }
    $after = Get-FenceState -Backend $Backend
    $errors = @($rows | Where-Object { $_.status -notin @('deleted', 'not_found') })
    return [ordered]@{ Ok = ($after.State -eq 'ABSENT'); Rows = $rows; Errors = $errors; StateAfter = $after; At = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
}

function Add-FenceSet {
    # The ONLY add path. Refuses without a valid proof token, refuses over any existing object, and rolls back (by key) if the add
    # throws or if the set read back is not PRESENT and persistent.
    param([Parameter(Mandatory)]$Backend, [Parameter(Mandatory)]$Plan, $Proof)
    $okProof = ($null -ne $Proof -and $Proof.PSObject.Properties['Kind'] -and $Proof.Kind -eq 'RollbackProof' -and $Proof.PSObject.Properties['Ok'] -and $Proof.Ok -eq $true)
    if (-not $okProof) { return [ordered]@{ Ok = $false; Refused = $true; Reason = 'refused: no valid rollback self-test proof (nothing added)'; Added = $false } }
    $pre = Get-FenceState -Backend $Backend
    if ($pre.State -ne 'ABSENT') { return [ordered]@{ Ok = $false; Refused = $true; Reason = "refused: fence state is $($pre.State) before the add (stale objects or an unreadable engine); run -Remove first (nothing added)"; Added = $false; StateBefore = $pre } }
    $ids = @()
    try { $ids = @($Backend.AddAll($Plan)) }
    catch {
        $rb = Remove-FenceSet -Backend $Backend
        return [ordered]@{ Ok = $false; Refused = $false; Reason = "add failed: $($_.Exception.Message); rolled back by key, state after: $($rb.StateAfter.State)"; Added = $false; Rollback = $rb }
    }
    $post = Get-FenceState -Backend $Backend
    if ($post.State -ne 'PRESENT' -or -not $post.AllPersistent) {
        $rb = Remove-FenceSet -Backend $Backend
        return [ordered]@{ Ok = $false; Refused = $false; Reason = "add reported success but the set read back is $($post.State), all persistent: $($post.AllPersistent); rolled back by key, state after: $($rb.StateAfter.State)"; Added = $false; Rollback = $rb; StateAfterAdd = $post }
    }
    return [ordered]@{ Ok = $true; Refused = $false; Reason = 'added: all four objects present and persistent'; Added = $true; FilterIds = $ids; StateAfterAdd = $post; At = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
}

# ---- backends -------------------------------------------------------------------------------------------------------------
function New-RealBackend {
    # Opens a NON-dynamic engine session. Requires Initialize-PersistType and an elevated 64-bit process.
    $eng = [BlarAI.WfpPersist.PersistEngine]::Open('BlarAI #1682 persist spike (non-dynamic session)')
    $be = [pscustomobject]@{ Kind = 'real'; Engine = $eng }
    $be | Add-Member -MemberType ScriptMethod -Name Flags -Value { param($kind, $key) [long]$this.Engine.Flags([string]$kind, [guid]$key) }
    $be | Add-Member -MemberType ScriptMethod -Name AddAll -Value { param($plan) @($this.Engine.AddAll($plan)) }
    $be | Add-Member -MemberType ScriptMethod -Name Delete -Value {
        param($kind, $key)
        $rc = [uint32]$this.Engine.Delete([string]$kind, [guid]$key)
        if ($rc -eq 0) { 'deleted' }
        elseif ($rc -in @([uint32]2150760451, [uint32]2150760453, [uint32]2150760455, [uint32]2150760456)) { 'not_found' }   # 0x80320003 / 05 / 07 / 08
        else { 'error: 0x{0:X8}' -f $rc }
    }
    $be | Add-Member -MemberType ScriptMethod -Name Close -Value { $this.Engine.Close() }
    return $be
}

function New-FakeBackend {
    # An in-memory stand-in with switchable failures; used only by -SelfTest. It never touches WFP.
    #   FailAddAfter  N  -> AddAll adds N objects (provider, sublayer, filters in that order) then throws: a half-failed, NON-atomic add
    #   FailDelete    keys whose Delete returns an error status
    #   Unreadable       -> Flags throws (engine cannot be queried)
    #   AddClearsFlags   -> AddAll "succeeds" but stores the objects without the persistent flag
    param([int]$FailAddAfter = -1, [string[]]$FailDelete = @(), [bool]$Unreadable = $false, [bool]$AddClearsFlags = $false)
    $order = @("provider|$($script:PersistProviderKey)", "sublayer|$($script:PersistSubLayerKey)") + @($script:PersistFilterKeys | ForEach-Object { "filter|$_" })
    $be = [pscustomobject]@{ Kind = 'fake'; Store = @{}; Calls = (New-Object System.Collections.ArrayList); FailAddAfter = $FailAddAfter; FailDelete = $FailDelete; Unreadable = $Unreadable; AddClearsFlags = $AddClearsFlags; AddOrder = $order }
    $be | Add-Member -MemberType ScriptMethod -Name Flags -Value {
        param($kind, $key)
        [void]$this.Calls.Add("flags $kind $key")
        if ($this.Unreadable) { throw 'fake engine unreadable' }
        $k = "$kind|$key"; if ($this.Store.ContainsKey($k)) { [long]$this.Store[$k] } else { [long]-1 }
    }
    $be | Add-Member -MemberType ScriptMethod -Name AddAll -Value {
        param($plan)
        [void]$this.Calls.Add('addall')
        $fl = $(if ($this.AddClearsFlags) { 0 } else { 1 })
        $n = 0
        foreach ($o in $this.AddOrder) {
            if ($this.FailAddAfter -ge 0 -and $n -ge $this.FailAddAfter) { throw "fake add failure after $n object(s)" }
            $this.Store[$o] = $fl; $n++
        }
        @(1, 2)
    }
    $be | Add-Member -MemberType ScriptMethod -Name Delete -Value {
        param($kind, $key)
        [void]$this.Calls.Add("delete $kind $key")
        if ($this.FailDelete -contains [string]$key) { return 'error: 0x80320006' }
        $k = "$kind|$key"; if ($this.Store.ContainsKey($k)) { $this.Store.Remove($k); 'deleted' } else { 'not_found' }
    }
    $be | Add-Member -MemberType ScriptMethod -Name Close -Value { [void]$this.Calls.Add('close') }
    return $be
}

# ---- filter export (read-only; needs elevation) ----------------------------------------------------------------------------
function Read-ExportText {
    param([byte[]]$Bytes)
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE) { return [Text.Encoding]::Unicode.GetString($Bytes) }
    return [Text.Encoding]::UTF8.GetString($Bytes)
}

function Get-FilterExportSummary {
    param([string]$Text, [string]$Marker, [string[]]$ExpectedKeys)
    $mc = if ($Text) { [regex]::Matches($Text, [regex]::Escape($Marker)).Count } else { 0 }
    $found = @(); $missing = @()
    foreach ($k in $ExpectedKeys) { if ($Text -and $Text.IndexOf($k, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $found += $k } else { $missing += $k } }
    return [ordered]@{ marker = $Marker; marker_count = $mc; keys_expected = @($ExpectedKeys); keys_found = $found; keys_missing = $missing; ok = ($mc -ge 1 -and $missing.Count -eq 0) }
}

function Invoke-PersistFilterExport {
    # `netsh wfp show filters file=<path>`, then the summary for our marker and the two filter keys. Reads the engine only.
    param([Parameter(Mandatory)][string]$Label, [Parameter(Mandatory)][string]$Path)
    $rec = [ordered]@{ label = $Label; at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); path = $Path; ok = $false; bytes = 0; sha256 = $null; summary = $null; error = $null; seconds = 0 }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $dir = Split-Path $Path -Parent; if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
        Assert-PlainOutputPath -Path $Path
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
        $p = Start-Process -FilePath "$env:SystemRoot\System32\netsh.exe" -ArgumentList @('wfp', 'show', 'filters', "file=`"$Path`"") -PassThru -WindowStyle Hidden
        if (-not $p.WaitForExit(120000)) { try { $p.Kill() } catch {}; throw 'netsh wfp show filters did not finish within 120 s' }
        if (-not (Test-Path -LiteralPath $Path)) { throw "netsh wrote no file (exit $($p.ExitCode))" }
        $bytes = [IO.File]::ReadAllBytes($Path)
        $sha = [Security.Cryptography.SHA256]::Create(); try { $rec.sha256 = ([BitConverter]::ToString($sha.ComputeHash($bytes))) -replace '-', '' } finally { $sha.Dispose() }
        $rec.bytes = $bytes.Length
        $rec.summary = Get-FilterExportSummary -Text (Read-ExportText $bytes) -Marker $script:PersistMarker -ExpectedKeys $script:PersistFilterKeys
        $rec.ok = [bool]$rec.summary.ok
    } catch { $rec.error = $_.Exception.Message }
    $rec.seconds = [Math]::Round($sw.Elapsed.TotalSeconds, 1)
    return $rec
}

function Get-BootTime { return ([datetimeoffset](Get-CimInstance Win32_OperatingSystem).LastBootUpTime) }

function Get-SafeSidProblems {
    # Wraps the wrapped script's Test-CoderSidSafe with the operator's token: [] means the target SID is safe to key a filter to.
    param([string]$Sid)
    $op = Get-OperatorTokenSids
    return @(Test-CoderSidSafe $Sid $op.User $op.Groups)
}

function Unregister-TaskIfPresent {
    # Removes a scheduled task by name; returns a short status string (never throws): unregistered | not_registered | error: ...
    param([Parameter(Mandatory)][string]$Name, [string]$Path = '\BlarAI\')
    try {
        if (-not (Get-ScheduledTask -TaskPath $Path -TaskName $Name -ErrorAction SilentlyContinue)) { return 'not_registered' }
        Unregister-ScheduledTask -TaskPath $Path -TaskName $Name -Confirm:$false -ErrorAction Stop
        return 'unregistered'
    } catch { return "error: $($_.Exception.Message)" }
}

# ---- admin-only folder check (SYSTEM and elevated tasks run scripts from a folder; nobody but administrators may be able to change it) ----
# Rights that let a principal change what a file or folder contains, who may use it, or who owns it (FileSystemRights bits).
$script:WriteRightsMask = 0x2 -bor 0x4 -bor 0x10 -bor 0x40 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40000000 -bor 0x10000000
# Rights on an ANCESTOR that let a principal delete or rename it away (and so replace the folder under it), delete children, or change inherited permissions or the owner.
# Create-files and append (add-subfolder) alone are fine on an ancestor: users have them on ProgramData and cannot replace a folder with them.
$script:AncestorRightsMask = 0x40 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000
$script:TrustedWriterSids = @('S-1-5-18', 'S-1-5-32-544', 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')   # SYSTEM, Administrators, TrustedInstaller

function Get-NonAdminWriteGrants {
    # PURE. $Rules: objects with Path, Sid, Type (Allow|Deny), Rights (int), Ancestor (bool), InheritOnly (bool). Returns one line per ALLOW rule that gives a
    # principal other than SYSTEM, Administrators and TrustedInstaller a right that can change the content (or, for an ancestor, delete or rename it away), plus a
    # line when the OWNER is not one of those three (an owner can rewrite the permissions). Deny rules are not credited (they can be bypassed by group membership in
    # ways this check cannot see), so they never excuse a grant. Inherit-only rules are skipped: their effect shows in the children's own ACLs, which are read too.
    param($Rules, [string]$OwnerSid, [string]$Path)
    $out = New-Object System.Collections.ArrayList
    if ($OwnerSid -and $script:TrustedWriterSids -notcontains $OwnerSid) { [void]$out.Add("$Path is owned by $OwnerSid (an owner can change its permissions)") }
    foreach ($r in @($Rules)) {
        if ($r.Type -ne 'Allow') { continue }
        if ($r.PSObject.Properties['InheritOnly'] -and $r.InheritOnly) { continue }
        if ($script:TrustedWriterSids -contains [string]$r.Sid) { continue }
        $mask = $(if ($r.Ancestor) { $script:AncestorRightsMask } else { $script:WriteRightsMask })
        $hit = ([int64]$r.Rights -band [int64]$mask)
        if ($hit -ne 0) { [void]$out.Add(("{0}: {1} is allowed rights 0x{2:X} ({3})" -f $r.Path, $r.Sid, [int64]$r.Rights, $(if ($r.Ancestor) { 'on an ancestor' } else { 'on the folder or a file in it' }))) }
    }
    return @($out)
}

function ConvertTo-AclRuleRows {
    # Turns a .NET security object's access rules into the rows Get-NonAdminWriteGrants reads.
    param($Security, [string]$Path, [bool]$Ancestor)
    $rows = @()
    foreach ($ar in $Security.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        $rows += [pscustomobject]@{ Path = $Path; Sid = $ar.IdentityReference.Value; Type = [string]$ar.AccessControlType; Rights = [int64]([int]$ar.FileSystemRights); Ancestor = $Ancestor; InheritOnly = [bool]([int]$ar.PropagationFlags -band 2) }
    }
    return $rows
}

function Get-PathSecurityObject {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Container) {
        $di = New-Object IO.DirectoryInfo $Path
        if ($di.PSObject.Methods['GetAccessControl']) { return $di.GetAccessControl() }
        return [IO.FileSystemAclExtensions]::GetAccessControl($di)
    }
    $fi = New-Object IO.FileInfo $Path
    if ($fi.PSObject.Methods['GetAccessControl']) { return $fi.GetAccessControl() }
    return [IO.FileSystemAclExtensions]::GetAccessControl($fi)
}

function Get-PathAttributes {
    # The path's OWN attributes (a link is not followed); $null when unreadable.
    param([string]$Path)
    try { return [IO.File]::GetAttributes($Path) } catch { return $null }
}

function Test-AdminOnlyFolder {
    # READ-ONLY. Ok only when the folder, every file in it and every ancestor give no non-administrator a write-class right (ancestors: delete, rename-away, delete-child,
    # change permissions, take ownership), none of them is owned by a non-administrator, and none of them is a reparse point (junction or symlink). A SYSTEM or elevated task
    # that runs a script from a folder this check fails is a privilege-escalation path for any non-elevated process of the operator. The two providers are injectable so
    # the self-tests can feed fabricated security descriptors and attributes.
    param([Parameter(Mandatory)][string]$Path, [scriptblock]$SecurityProvider = { param($p) Get-PathSecurityObject -Path $p }, [scriptblock]$AttributeProvider = { param($p) Get-PathAttributes -Path $p })
    $problems = New-Object System.Collections.ArrayList; $checked = 0
    $reparse = [int][IO.FileAttributes]::ReparsePoint
    try {
        $full = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
        $items = @($full) + @(Get-ChildItem -LiteralPath $full -Recurse -Force -ErrorAction Stop | ForEach-Object { $_.FullName })
        foreach ($i in $items) {
            $sec = & $SecurityProvider $i; $checked++
            $owner = $null; try { $owner = $sec.GetOwner([Security.Principal.SecurityIdentifier]).Value } catch {}
            foreach ($g in (Get-NonAdminWriteGrants -Rules (ConvertTo-AclRuleRows -Security $sec -Path $i -Ancestor $false) -OwnerSid $owner -Path $i)) { [void]$problems.Add($g) }
            $attr = & $AttributeProvider $i
            if ($null -ne $attr -and (([int]$attr) -band $reparse)) { [void]$problems.Add("$i is a reparse point (junction or symlink)") }
        }
        $parent = Split-Path $full -Parent
        while ($parent) {
            $sec = & $SecurityProvider $parent; $checked++
            $owner = $null; try { $owner = $sec.GetOwner([Security.Principal.SecurityIdentifier]).Value } catch {}
            foreach ($g in (Get-NonAdminWriteGrants -Rules (ConvertTo-AclRuleRows -Security $sec -Path $parent -Ancestor $true) -OwnerSid $owner -Path $parent)) { [void]$problems.Add($g) }
            $attr = & $AttributeProvider $parent
            if ($null -ne $attr -and (([int]$attr) -band $reparse)) { [void]$problems.Add("$parent is a reparse point (junction or symlink)") }
            $next = Split-Path $parent -Parent
            if ($next -eq $parent) { break }
            $parent = $next
        }
    } catch { [void]$problems.Add("the folder's permissions could not be read ($($_.Exception.Message)): treated as not admin-only") }
    return [ordered]@{ Ok = ($problems.Count -eq 0); Problems = @($problems); Checked = $checked; Path = $Path }
}

# ---- the independent rollback: no dependence on the wrapped script (used when it cannot be read, parsed or hashed) ------------
function ConvertFrom-ManualRollbackOutput {
    # PURE. The text ManualWfpRollback.Run() returns: one line per object ("filter <key> 0x00000000", "sublayer 0x...", "provider 0x...").
    # Ok only when all four rows are present and every status is 0 (deleted) or a not-found status (already gone).
    param([string]$Text)
    $rows = @()
    foreach ($l in ($Text -split "`r?`n")) {
        if ($l -match '^(filter|sublayer|provider)\s+(?:([0-9a-fA-F-]{36})\s+)?0x([0-9A-Fa-f]{8})\s*$') {
            $st = [uint32]('0x' + $Matches[3])
            $good = ($st -eq 0 -or $st -in @([uint32]2150760451, [uint32]2150760453, [uint32]2150760455, [uint32]2150760456))
            $rows += [ordered]@{ kind = $Matches[1]; key = $Matches[2]; status = ('0x' + $Matches[3].ToUpper()); ok = $good }
        }
    }
    $okAll = ($rows.Count -eq 4 -and @($rows | Where-Object { -not $_.ok }).Count -eq 0)
    return [ordered]@{ Ok = $okAll; Rows = $rows; Reason = $(if ($okAll) { 'all four deleted or already gone' } elseif ($rows.Count -ne 4) { "expected 4 status rows, parsed $($rows.Count): $Text" } else { 'a delete returned an error status' }) }
}

function Invoke-ManualRollback {
    # Compiles the self-contained snippet and runs it (elevated, 64-bit). It reads nothing from disk but this library's own text, so it still
    # works when the wrapped script is missing, unparseable or pinned to a different hash. It cannot read the state back; the statuses are its evidence.
    if (-not [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { return [ordered]@{ Ok = $false; Rows = @(); Reason = 'not elevated' } }
    try {
        $cs = [regex]::Match($script:ManualRollbackSnippet, '(?s)@"\r?\n(.*?)\r?\n"@').Groups[1].Value
        if (-not ('ManualWfpRollback' -as [type])) { Add-Type -TypeDefinition $cs -Language CSharp }
        return (ConvertFrom-ManualRollbackOutput -Text ([ManualWfpRollback]::Run()))
    } catch { return [ordered]@{ Ok = $false; Rows = @(); Reason = "manual rollback failed: $($_.Exception.Message)" } }
}

function Test-ArmExpired {
    # PURE. True when the arm state is older than $Hours (a startup task left over from an arming that never completed must not live forever).
    param($Armed, [int]$Hours, [datetimeoffset]$Now = [datetimeoffset]::Now)
    if (-not $Armed -or -not $Armed.armed_at) { return $false }
    try { return (($Now - (ConvertTo-DateTimeOffset $Armed.armed_at)).TotalHours -gt $Hours) } catch { return $false }
}

function Get-CodeSetId {
    # PURE. One identifier for a set of file hashes: SHA-256 of the sorted "name=hash" lines. The SYSTEM tasks carry the id taken at arming and refuse to run
    # with a code set that hashes to anything else.
    param([Parameter(Mandatory)]$Hashes)
    $lines = @($Hashes.Keys | Sort-Object | ForEach-Object { "$_=$($Hashes[$_])" })
    return (Get-NormalizedSha256FromBytes -Bytes ([Text.Encoding]::UTF8.GetBytes(($lines -join "`n") + "`n")))
}

function Test-CodeSetId {
    # The code set in $Folder (libraries this process loaded: the hashes of the bytes it ran; the others from disk) must hash to $Expected.
    param([Parameter(Mandatory)][string]$Folder, [Parameter(Mandatory)][string]$Expected)
    $cs = Get-CodeSetHashes -Folder $Folder
    if ($cs.Missing.Count) { return [ordered]@{ Ok = $false; Reason = "code-set file(s) missing: $($cs.Missing -join ', ')" } }
    $id = Get-CodeSetId -Hashes $cs.Hashes
    if ($id -ne $Expected.ToUpperInvariant()) { return [ordered]@{ Ok = $false; Reason = "the code set hashes to $id, not the $($Expected.ToUpperInvariant()) taken at arming: a script changed since" } }
    return [ordered]@{ Ok = $true; Reason = 'code set equals the one taken at arming'; Id = $id }
}

# ---- elevated writes into folders other processes may be able to change ------------------------------------------------------------
function Assert-PlainOutputPath {
    # An elevated or SYSTEM process is about to create or overwrite $Path. Refuse when the file, its folder or ANY ancestor is a reparse point (junction or
    # symlink: the write would land somewhere else with elevated rights), or when an existing file has more than one hard link. Throws; the caller fails closed.
    param([Parameter(Mandatory)][string]$Path)
    if (Test-PathExistsNoFollow $Path) {
        if (Test-IsReparsePoint $Path) { throw "refusing to write '$Path': it is a reparse point (junction or symlink)" }
        if ((Get-FileLinkCount $Path) -gt 1) { throw "refusing to write '$Path': it has more than one hard link" }
    }
    $dir = Split-Path $Path -Parent
    while ($dir) {
        if ((Test-PathExistsNoFollow $dir) -and (Test-IsReparsePoint $dir)) { throw "refusing to write '$Path': '$dir' is a reparse point (junction or symlink)" }
        $up = Split-Path $dir -Parent
        if ($up -eq $dir) { break }
        $dir = $up
    }
}

function Write-JsonGuarded {
    # Write-JsonAtomic behind Assert-PlainOutputPath (for the file and its .tmp). The arm 3 scripts use this for every record an elevated or SYSTEM process writes.
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$Object, [int]$Depth = 12)
    Assert-PlainOutputPath -Path $Path
    Assert-PlainOutputPath -Path "$Path.tmp"
    Write-JsonAtomic -Path $Path -Object $Object -Depth $Depth
}

function Test-ProofLocation {
    # The proof is trusted only if nobody but administrators can write it: its folder (beside the scripts or elsewhere) must be admin-only, also for an attended run.
    # Returns problems. The checker is injectable for the self-tests.
    param([Parameter(Mandatory)][string]$ProofPath, [Parameter(Mandatory)][string]$ScriptFolder, [scriptblock]$Checker = { param($p) Test-AdminOnlyFolder -Path $p })
    $dir = Split-Path $ProofPath -Parent
    $ao = & $Checker $dir
    if ($ao.Ok) { return @() }
    return @("the proof file's folder '$dir' is not admin-only, so the proof could have been written by anyone") + @($ao.Problems | Select-Object -First 3)
}

# ---- the recorded decision that arm 3b needs ----
$script:RestartDecisionFile = 'arm3b-restart-decision.json'
function Test-RestartDecision {
    # READ-ONLY. Arm 3b closes every application WITHOUT forewarning when its restart timer ends (shutdown with a timeout above 0 implies /f). Running it needs the Lead Architect's
    # recorded decision: this file in the script folder (which must be admin-only) with decision = accept-forced-restart, who decided, when (not in the future, not older than
    # $MaxAgeDays) and a reference to where the decision is recorded (for example a comment on #1682). An administrator writes it; nothing in these scripts does.
    param([Parameter(Mandatory)][string]$Folder, [datetimeoffset]$Now = [datetimeoffset]::Now, [int]$MaxAgeDays = 14)
    $p = Join-Path $Folder $script:RestartDecisionFile
    if (-not (Test-Path -LiteralPath $p)) { return [ordered]@{ Ok = $false; Reason = "no recorded decision: $p does not exist (the 3b restart is forced; see DESIGN.md section 7)" } }
    $d = $null
    try { $d = ConvertFrom-Json ([IO.File]::ReadAllText($p)) } catch { return [ordered]@{ Ok = $false; Reason = "the decision file does not parse: $($_.Exception.Message)" } }
    if ([string]$d.decision -ne 'accept-forced-restart') { return [ordered]@{ Ok = $false; Reason = "the decision file does not say decision = accept-forced-restart (it says '$($d.decision)')" } }
    if (-not [string]$d.decided_by) { return [ordered]@{ Ok = $false; Reason = 'the decision file names nobody in decided_by' } }
    if (-not [string]$d.reference) { return [ordered]@{ Ok = $false; Reason = 'the decision file has no reference to where the decision is recorded' } }
    $at = $null
    try { $at = $(if ($d.decided_at -is [datetime]) { [datetimeoffset]$d.decided_at } else { [datetimeoffset]::Parse([string]$d.decided_at) }) } catch { return [ordered]@{ Ok = $false; Reason = 'decided_at is missing or not a date' } }
    $age = ($Now - $at).TotalDays
    if ($age -lt -0.01) { return [ordered]@{ Ok = $false; Reason = 'decided_at is in the future' } }
    if ($age -gt $MaxAgeDays) { return [ordered]@{ Ok = $false; Reason = ("the decision is {0:N1} days old (limit {1}): record it again" -f $age, $MaxAgeDays) } }
    return [ordered]@{ Ok = $true; Reason = "decision recorded by $($d.decided_by) at $($at.ToString('o')) ($($d.reference))" }
}
