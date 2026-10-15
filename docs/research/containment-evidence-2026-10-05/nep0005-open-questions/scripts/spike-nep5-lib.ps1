#requires -Version 5.1
<#
.SYNOPSIS
  NEP-0005 open-questions matrix, library 1 of 2: the recorded constants, the harness contract (how this side calls `halfset`
  and reads what it prints), our own adder (C#), the direct sweep, removal by key, the proof-gated add paths, the rollback proof
  and the fakes the self-tests run against. Dot-source it AFTER spike-lib.ps1, spike-persist-lib.ps1 and spike-task-driver.ps1 and
  after Import-WfpHelpers has run; it has no side effects on load and opens no WFP engine until a backend is created.

.DESCRIPTION
  Three sublayers are the ONLY ones any code here may add to or delete from: S1 (srt-win harness), S2 (our own four-object set),
  S3 (the different-sublayer case). A filter of ours or srt-win's found under any other sublayer is a STOP, never a cleanup.

  Seams (everything below that touches the machine goes through one of them, so -SelfTest drives the logic against fakes):
    Runner    scriptblock { param([string[]]$Argv) } -> @{ ExitCode; Stdout; Stderr; TimedOut }: the harness. New-HalfsetRunner is the real one
              (hash-checked before every run); New-FakeHalfset is an in-memory stand-in over a fake world.
    Backend   our own engine: Flags(kind, key) (-1 when absent), AddSet(plan), AddOne(filter), Delete(kind, key), Close(). New-Nep5RealBackend wraps
              the C# engine (a NON-dynamic session); New-Nep5FakeBackend is the in-memory store.
    Exporter  scriptblock { param($Label) } -> @{ ok; text; ... }: `netsh wfp show filters`.

  Gates in front of every add: a valid proof token (Test-N5Proof; the token carries a per-process nonce, so a hand-made object is refused),
  the SID allowlist (blarai-spike or the stale test SID only; the operator's SID and every group in his token are refused), the sublayer
  allowlist, and an empty sweep. Each gate takes its validator as a parameter so a test can switch it off and show the bad outcome is
  then reachable (a control is tested ON and tested OFF).
#>

# ---- recorded constants (fixed in this file; never generated at run time) -------------------------------------------------
$script:N5Marker = 'BlarAI #1763'
$script:N5SpikeSid = 'S-1-5-21-1000000001-1000000002-1000000003-1271'
$script:N5StaleSid = 'S-1-5-21-17630000-17630001-17630002-91763'
$script:N5SubLayers = [ordered]@{ S1 = 'c971a69f-d6ab-4885-9b49-506d8aa51c86'; S2 = '3e29ae7e-fd9f-413a-8b8d-da9bd3a96359'; S3 = '6cf901ba-a6cd-4846-81a5-2598c55bdef5' }
$script:N5SrtDefaultSubLayer = '2c5d0ad6-5f3b-4d4e-9b8f-1a3e7c9d0b21'
$script:N5OldArm3SubLayer = '7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02'
$script:N5OldArm3Provider = '7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f01'
$script:N5ProviderKey = '3e29ae7e-fd9f-413a-8b8d-da9bd3a96360'
$script:N5ProviderName = 'BlarAI #1763 provider'
# Never added as a sublayer: only NAMED by the one attempt row that must be refused by the engine.
$script:N5MissingSubLayer = '3e29ae7e-fd9f-413a-8b8d-da9bd3a96361'
$script:N5PinnedSrtSha = '24eb39e94a6de386e83d126c52317d8e0fa49522'
$script:N5PinnedCargoLockSha256 = 'C41CF41050C2B1E2986ED7CA690A703415CABADFED9219788A451DF0DA0967EC'   # raw bytes, the pinned vendor/srt-win-src Cargo.lock
$script:N5PortOut = 61763; $script:N5PortNeighbour = 61764; $script:N5PortIn = 60085   # out of range, its neighbour, inside srt-win's permit range 60080-60089
$script:N5LayerV4 = 'c38d57d1-05a7-4c33-904f-7fbceee60e82'; $script:N5LayerV6 = '4a72393b-319f-44bc-84c3-ba54dcb3b6b4'
# Our own filter keys, one per row object. Fixed so that removal works with no memory of the run that added them.
$script:N5FilterKeys = [ordered]@{
    's2-block-v4'            = 'f1763001-0000-4d8e-9a31-2b6d4c8e0001'
    's2-block-v6'            = 'f1763001-0000-4d8e-9a31-2b6d4c8e0002'
    's2-permit-v4'           = 'f1763001-0000-4d8e-9a31-2b6d4c8e0003'
    's2-exactport-permit-v4' = 'f1763001-0000-4d8e-9a31-2b6d4c8e0004'
    's2-noprov-block-v4'     = 'f1763001-0000-4d8e-9a31-2b6d4c8e0005'
    's2-missing-sublayer-v4' = 'f1763001-0000-4d8e-9a31-2b6d4c8e0006'
    's2-n1-probe-v4'         = 'f1763001-0000-4d8e-9a31-2b6d4c8e0021'   # what the account's own token tries to add in N1 (never added by us)
    's3-block-v4'            = 'f1763001-0000-4d8e-9a31-2b6d4c8e0011'
    's3-block-v6'            = 'f1763001-0000-4d8e-9a31-2b6d4c8e0012'
}
$script:N5BlockWeight = 0x1000; $script:N5PermitWeight = 0x2000
# harness exit codes (halfset README): the meaning of every code this side knows.
$script:N5HarnessExit = @{ 0 = 'ok'; 1 = 'selftest_failed'; 2 = 'usage'; 3 = 'sublayer_refused'; 4 = 'sid_refused'; 5 = 'sublayer_not_empty'; 6 = 'not_elevated_engine_unreadable'
                           7 = 'engine_denied'; 8 = 'readback_mismatch'; 9 = 'stop_foreign_filter'; 10 = 'engine_error'; 11 = 'delete_target_not_under_sublayer'; 12 = 'not_armed'; 13 = 'trace_failed' }
# The four verbs that change the engine: the harness refuses them (exit 12) without `--live <proof.json>`; status and enum reject --live. $script:N5LiveProof is the one
# harness proof file (written only by -SelfTest -WriteProof, beside these scripts); Invoke-Halfset appends it, after validation, to those four verbs and to nothing else.
$script:N5MutatingVerbs = @('install', 'delete-filter', 'delete-sublayer', 'uninstall')
$script:N5LiveProof = $null
$script:N5HarnessVerbs = @('install', 'status', 'enum', 'delete-filter', 'delete-sublayer', 'uninstall', 'selftest-refusals', '--version')

function Get-N5Now { return (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }

function ConvertTo-N5Guid {
    # PURE. Canonical lowercase GUID text, or $null when the text is not a GUID (never throws).
    param($Text)
    $g = [guid]::Empty
    if ([guid]::TryParse([string]$Text, [ref]$g)) { return $g.ToString() }
    return $null
}

function Get-N5SubLayerId {
    # PURE. 'S1' | 'S2' | 'S3' for an allowed sublayer GUID (any case, braces allowed), else $null.
    param($Key)
    $k = ConvertTo-N5Guid $Key
    if (-not $k) { return $null }
    foreach ($id in $script:N5SubLayers.Keys) { if ($script:N5SubLayers[$id] -eq $k) { return $id } }
    return $null
}

# ---- the C# (appended to the wrapped #1671 source so it can reuse its structs and Native imports) --------------------------
$script:N5CSharp = @'

namespace BlarAI.Nep5
{
    using System;
    using System.Collections.Generic;
    using System.Runtime.InteropServices;
    using System.Text;
    using BlarAI.Wfp;

    public static class N5Native
    {
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmFilterDeleteByKey0(IntPtr engineHandle, ref Guid key);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmSubLayerDeleteByKey0(IntPtr engineHandle, ref Guid key);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmProviderDeleteByKey0(IntPtr engineHandle, ref Guid key);
    }

    public static class N5Keys
    {
        public static readonly Guid S1 = new Guid("c971a69f-d6ab-4885-9b49-506d8aa51c86");
        public static readonly Guid S2 = new Guid("3e29ae7e-fd9f-413a-8b8d-da9bd3a96359");
        public static readonly Guid S3 = new Guid("6cf901ba-a6cd-4846-81a5-2598c55bdef5");
        public static readonly Guid MissingSubLayer = new Guid("3e29ae7e-fd9f-413a-8b8d-da9bd3a96361");
        public static readonly Guid Provider = new Guid("3e29ae7e-fd9f-413a-8b8d-da9bd3a96360");
        // um/fwpmu.h: FWPM_CONDITION_IP_REMOTE_ADDRESS, FWPM_CONDITION_IP_REMOTE_PORT (read from the installed SDK 10.0.26100.0).
        public static readonly Guid CondRemoteAddress = new Guid("b235ae9a-1d64-49b8-a44c-5ff3d9095045");
        public static readonly Guid CondRemotePort = new Guid("c35a604d-d22b-4e1a-91b4-68f674ee674b");
        public const string SpikeSid = "S-1-5-21-1000000001-1000000002-1000000003-1271";
        public const string StaleSid = "S-1-5-21-17630000-17630001-17630002-91763";
        public const string Marker = "BlarAI #1763";
        public const string ProviderName = "BlarAI #1763 provider";
        // fwpmtypes.h: the persistent flag is 0x1 on providers, sublayers and filters. fwptypes.h: FWP_UINT16 = 2.
        public const uint Persistent = 1, FWP_UINT16 = 2;
        public const uint NotFoundFilter = 0x80320003, NotFoundProvider = 0x80320005, NotFoundSubLayer = 0x80320007, NotFoundGeneric = 0x80320008;
        public static bool IsAllowedSubLayer(Guid g) { return g == S1 || g == S2 || g == S3; }
        public static bool IsAllowedSid(string s) { return s == SpikeSid || s == StaleSid; }
    }

    public sealed class N5Filter
    {
        public Guid Key; public string Name; public bool V6; public bool Permit; public string UserSid;
        public bool HasRemote; public uint RemoteAddr; public ushort RemotePort; public Guid SubLayer; public bool UseProvider;
        public bool AttemptMissing; public ulong Weight;
    }

    public sealed class N5Set
    {
        public bool AddProvider; public bool AddSubLayer; public Guid SubLayer; public bool SubLayerUsesProvider;
        public List<N5Filter> Filters = new List<N5Filter>();

        // Every refusal here is in front of any marshalling or engine call.
        public static void ValidateFilter(N5Filter f)
        {
            if (f == null) throw new ArgumentException("null filter");
            if (f.Name == null || !f.Name.StartsWith(N5Keys.Marker)) throw new ArgumentException("every display name carries the marker: " + f.Name);
            if (f.AttemptMissing)
            {
                if (f.SubLayer != N5Keys.MissingSubLayer) throw new ArgumentException("an attempt row may only name the recorded missing sublayer");
                if (f.UseProvider) throw new ArgumentException("the missing-sublayer attempt carries no provider");
            }
            else if (!N5Keys.IsAllowedSubLayer(f.SubLayer)) throw new ArgumentException("refusing sublayer " + f.SubLayer + " (only S1, S2, S3)");
            if (!string.IsNullOrEmpty(f.UserSid) && !N5Keys.IsAllowedSid(f.UserSid)) throw new ArgumentException("refusing SID (only the test account and the stale test SID): " + f.UserSid);
            if (f.HasRemote && f.V6) throw new ArgumentException("the remote address condition is IPv4 only");
            if (string.IsNullOrEmpty(f.UserSid) && !f.HasRemote) throw new ArgumentException("a filter with no condition would match everyone: refused");
            if (!f.Permit && string.IsNullOrEmpty(f.UserSid)) throw new ArgumentException("a BLOCK filter must carry the user condition (it could cut the operator off): refused");
        }

        public void Validate()
        {
            if (AddSubLayer && !N5Keys.IsAllowedSubLayer(SubLayer)) throw new ArgumentException("refusing sublayer " + SubLayer + " (only S1, S2, S3)");
            if (SubLayerUsesProvider && !AddProvider) throw new ArgumentException("the sublayer names a provider that the set does not add");
            foreach (N5Filter f in Filters)
            {
                ValidateFilter(f);
                if (f.AttemptMissing) throw new ArgumentException("an attempt filter cannot be part of an add set");
                if (AddSubLayer && f.SubLayer != SubLayer) throw new ArgumentException("a filter names a different sublayer than the set adds");
            }
        }
    }

    // All unmanaged memory for one add. BFE copies everything during Add, so Free() after the transaction is safe.
    public sealed class N5Marshal
    {
        public List<IntPtr> Allocs = new List<IntPtr>();
        public FWPM_PROVIDER0 Provider; public FWPM_SUBLAYER0 SubLayer; public List<FWPM_FILTER0> Filters = new List<FWPM_FILTER0>();
        public List<List<FWPM_FILTER_CONDITION0>> Conditions = new List<List<FWPM_FILTER_CONDITION0>>();
        IntPtr provKeyPtr = IntPtr.Zero;

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

        public static N5Marshal Build(N5Set set)
        {
            set.Validate();
            N5Marshal m = new N5Marshal();
            m.provKeyPtr = m.GuidPtr(N5Keys.Provider);
            if (set.AddProvider)
            {
                m.Provider = new FWPM_PROVIDER0(); m.Provider.providerKey = N5Keys.Provider; m.Provider.flags = N5Keys.Persistent;
                m.Provider.displayData = m.DD(N5Keys.ProviderName, "Persistent provider for the NEP-0005 open-questions matrix; removed by key.");
            }
            if (set.AddSubLayer)
            {
                m.SubLayer = new FWPM_SUBLAYER0(); m.SubLayer.subLayerKey = set.SubLayer; m.SubLayer.flags = N5Keys.Persistent;
                m.SubLayer.providerKey = set.SubLayerUsesProvider ? m.provKeyPtr : IntPtr.Zero;
                m.SubLayer.displayData = m.DD(N5Keys.Marker + " sublayer", "Persistent sublayer for the NEP-0005 open-questions matrix; removed by key.");
                m.SubLayer.weight = Plan.SubLayerWeight;
            }
            foreach (N5Filter f in set.Filters) m.AddFilter(f);
            return m;
        }

        public static N5Marshal BuildOne(N5Filter f)
        {
            N5Set.ValidateFilter(f);
            N5Marshal m = new N5Marshal(); m.provKeyPtr = m.GuidPtr(N5Keys.Provider); m.AddFilter(f); return m;
        }

        void AddFilter(N5Filter f)
        {
            List<FWPM_FILTER_CONDITION0> conds = new List<FWPM_FILTER_CONDITION0>();
            if (f.HasRemote)
            {
                FWPM_FILTER_CONDITION0 a = new FWPM_FILTER_CONDITION0(); a.fieldKey = N5Keys.CondRemoteAddress; a.matchType = Plan.FWP_MATCH_EQUAL;
                a.conditionValue.type = Plan.FWP_UINT32; a.conditionValue.value = new IntPtr(unchecked((int)f.RemoteAddr)); conds.Add(a);
                FWPM_FILTER_CONDITION0 p = new FWPM_FILTER_CONDITION0(); p.fieldKey = N5Keys.CondRemotePort; p.matchType = Plan.FWP_MATCH_EQUAL;
                p.conditionValue.type = N5Keys.FWP_UINT16; p.conditionValue.value = new IntPtr((int)f.RemotePort); conds.Add(p);
            }
            if (!string.IsNullOrEmpty(f.UserSid))
            {
                IntPtr sdBlob = Blob(Plan.BuildSd(f.UserSid));
                FWPM_FILTER_CONDITION0 u = new FWPM_FILTER_CONDITION0(); u.fieldKey = Plan.CondAleUserId; u.matchType = Plan.FWP_MATCH_EQUAL;
                u.conditionValue.type = Plan.FWP_SECURITY_DESCRIPTOR_TYPE; u.conditionValue.value = sdBlob; conds.Add(u);
            }
            int condSize = Marshal.SizeOf(typeof(FWPM_FILTER_CONDITION0));
            IntPtr arr = A(condSize * conds.Count);
            for (int i = 0; i < conds.Count; i++) Marshal.StructureToPtr(conds[i], new IntPtr(arr.ToInt64() + (long)i * condSize), false);
            FWPM_FILTER0 fl = new FWPM_FILTER0(); fl.filterKey = f.Key; fl.displayData = DD(f.Name, "Persistent filter for the NEP-0005 open-questions matrix.");
            fl.flags = N5Keys.Persistent; fl.providerKey = f.UseProvider ? provKeyPtr : IntPtr.Zero;
            fl.layerKey = f.V6 ? Plan.LayerConnectV6 : Plan.LayerConnectV4; fl.subLayerKey = f.SubLayer;
            fl.weight.type = Plan.FWP_UINT64; fl.weight.value = U64(f.Weight);
            fl.numFilterConditions = (uint)conds.Count; fl.filterCondition = arr; fl.action.type = f.Permit ? Plan.FWP_ACTION_PERMIT : Plan.FWP_ACTION_BLOCK;
            Filters.Add(fl); Conditions.Add(conds);
        }

        public void Free() { foreach (IntPtr p in Allocs) Marshal.FreeHGlobal(p); Allocs.Clear(); }
    }

    // A NON-dynamic engine session: what it adds persists. Reads and deletes treat "not found" as a normal answer.
    public sealed class N5Engine
    {
        IntPtr handle; readonly object gate = new object();
        public bool IsOpen { get { lock (gate) { return handle != IntPtr.Zero; } } }

        public static N5Engine Open(string name)
        {
            FWPM_SESSION0 s = new FWPM_SESSION0();
            IntPtr nm = Marshal.StringToHGlobalUni(name);
            try
            {
                s.displayData.name = nm; s.flags = 0; s.txnWaitTimeoutInMSec = 10000;
                IntPtr h;
                uint rc = Native.FwpmEngineOpen0(null, 0xFFFFFFFF, IntPtr.Zero, ref s, out h);
                if (rc != 0) throw new InvalidOperationException("FwpmEngineOpen0 failed 0x" + rc.ToString("X8"));
                N5Engine e = new N5Engine(); e.handle = h; return e;
            }
            finally { Marshal.FreeHGlobal(nm); }
        }

        public void Close() { lock (gate) { if (handle == IntPtr.Zero) return; Native.FwpmEngineClose0(handle); handle = IntPtr.Zero; } }

        static void Check(string what, uint rc) { if (rc != 0) throw new InvalidOperationException(what + " failed 0x" + rc.ToString("X8")); }

        // One transaction: provider, sublayer, filters. Throws (after aborting) on any failure; the caller rolls back by key.
        public ulong[] AddSet(N5Set set)
        {
            N5Marshal m = N5Marshal.Build(set); bool inTxn = false; List<ulong> ids = new List<ulong>();
            try
            {
                lock (gate)
                {
                    if (handle == IntPtr.Zero) throw new InvalidOperationException("engine closed");
                    Check("FwpmTransactionBegin0", Native.FwpmTransactionBegin0(handle, 0)); inTxn = true;
                    if (set.AddProvider) { FWPM_PROVIDER0 p = m.Provider; Check("FwpmProviderAdd0", Native.FwpmProviderAdd0(handle, ref p, IntPtr.Zero)); }
                    if (set.AddSubLayer) { FWPM_SUBLAYER0 sl = m.SubLayer; Check("FwpmSubLayerAdd0", Native.FwpmSubLayerAdd0(handle, ref sl, IntPtr.Zero)); }
                    foreach (FWPM_FILTER0 f0 in m.Filters) { FWPM_FILTER0 f = f0; ulong id; Check("FwpmFilterAdd0", Native.FwpmFilterAdd0(handle, ref f, IntPtr.Zero, out id)); ids.Add(id); }
                    Check("FwpmTransactionCommit0", Native.FwpmTransactionCommit0(handle)); inTxn = false;
                }
            }
            catch { if (inTxn) { lock (gate) { if (handle != IntPtr.Zero) Native.FwpmTransactionAbort0(handle); } } throw; }
            finally { m.Free(); }
            return ids.ToArray();
        }

        // ONE filter in its own transaction. An engine refusal is the RESULT (returned as text), not an exception; validation failures still throw.
        public string AddOne(N5Filter f)
        {
            N5Marshal m = N5Marshal.BuildOne(f); bool inTxn = false;
            try
            {
                lock (gate)
                {
                    if (handle == IntPtr.Zero) return "error: engine closed";
                    uint rc = Native.FwpmTransactionBegin0(handle, 0);
                    if (rc != 0) return "error: FwpmTransactionBegin0 0x" + rc.ToString("X8");
                    inTxn = true;
                    FWPM_FILTER0 fl = m.Filters[0]; ulong id;
                    rc = Native.FwpmFilterAdd0(handle, ref fl, IntPtr.Zero, out id);
                    if (rc != 0) { Native.FwpmTransactionAbort0(handle); inTxn = false; return "error: FwpmFilterAdd0 0x" + rc.ToString("X8"); }
                    rc = Native.FwpmTransactionCommit0(handle);
                    if (rc != 0) { Native.FwpmTransactionAbort0(handle); inTxn = false; return "error: FwpmTransactionCommit0 0x" + rc.ToString("X8"); }
                    inTxn = false; return "added";
                }
            }
            finally { if (inTxn) { lock (gate) { if (handle != IntPtr.Zero) Native.FwpmTransactionAbort0(handle); } } m.Free(); }
        }

        static uint NotFoundFor(string kind)
        {
            if (kind == "filter") return N5Keys.NotFoundFilter;
            if (kind == "provider") return N5Keys.NotFoundProvider;
            if (kind == "sublayer") return N5Keys.NotFoundSubLayer;
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
            if (rc == nf || rc == N5Keys.NotFoundGeneric) return -1;
            if (rc != 0) throw new InvalidOperationException(kind + " lookup failed 0x" + rc.ToString("X8"));
            try
            {
                if (kind == "filter") return ((FWPM_FILTER0)Marshal.PtrToStructure(o, typeof(FWPM_FILTER0))).flags;
                if (kind == "provider") return ((FWPM_PROVIDER0)Marshal.PtrToStructure(o, typeof(FWPM_PROVIDER0))).flags;
                return ((FWPM_SUBLAYER0)Marshal.PtrToStructure(o, typeof(FWPM_SUBLAYER0))).flags;
            }
            finally { Native.FwpmFreeMemory0(ref o); }
        }

        // Deletes ONE object by key, outside any transaction. Returns the raw status.
        public uint Delete(string kind, Guid key)
        {
            NotFoundFor(kind);
            lock (gate)
            {
                if (handle == IntPtr.Zero) throw new InvalidOperationException("engine closed");
                if (kind == "filter") return N5Native.FwpmFilterDeleteByKey0(handle, ref key);
                if (kind == "provider") return N5Native.FwpmProviderDeleteByKey0(handle, ref key);
                return N5Native.FwpmSubLayerDeleteByKey0(handle, ref key);
            }
        }
    }
}
'@

function Initialize-Nep5Type {
    # Compiles the wrapped source and this library's namespace as ONE unit (the new types reuse the wrapped structs). No engine is opened.
    if (-not $script:csharp) { throw 'Import-WfpHelpers must run first' }
    if (-not ('BlarAI.Nep5.N5Engine' -as [type])) {
        if ('BlarAI.Wfp.Plan' -as [type]) { throw 'BlarAI.Wfp is already loaded without the nep5 types in this session: start a fresh PowerShell' }
        Add-Type -TypeDefinition ($script:csharp + $script:N5CSharp) -Language CSharp
    }
}

# ---- the independent rollback: needs nothing from this folder (printed by -DryRun and the README; compiled, never run, by -SelfTest) --------
# Enumerates EVERY filter, deletes those under S1/S2/S3 by key, reports (never deletes) a filter of ours or srt-win's anywhere else, then deletes the
# three sublayers and the provider by key.
$script:N5ManualRollbackSnippet = @'
Add-Type -TypeDefinition @"
using System; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class ManualNep5Rollback {
  [StructLayout(LayoutKind.Sequential)] struct NAME { public IntPtr n; public IntPtr d; }
  [StructLayout(LayoutKind.Sequential)] struct BLOB { public uint size; public IntPtr data; }
  [StructLayout(LayoutKind.Sequential)] struct VAL { public uint type; public IntPtr value; }
  [StructLayout(LayoutKind.Sequential)] struct ACT { public uint type; public Guid ft; }
  [StructLayout(LayoutKind.Sequential)] struct CTX { public ulong a; public ulong b; }
  [StructLayout(LayoutKind.Sequential)] struct SESSION { public Guid k; public NAME dd; public uint flags; public uint txn; public uint pid; public IntPtr sid; public IntPtr user; public int kernel; }
  [StructLayout(LayoutKind.Sequential)] struct FILTER {
    public Guid filterKey; public NAME displayData; public uint flags; public IntPtr providerKey; public BLOB providerData; public Guid layerKey; public Guid subLayerKey;
    public VAL weight; public uint numFilterConditions; public IntPtr filterCondition; public ACT action; public CTX context; public IntPtr reserved; public ulong filterId; public VAL effectiveWeight; }
  [DllImport("fwpuclnt.dll", CharSet = CharSet.Unicode)] static extern uint FwpmEngineOpen0(string s, uint a, IntPtr i, ref SESSION se, out IntPtr h);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmEngineClose0(IntPtr h);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmFilterCreateEnumHandle0(IntPtr h, IntPtr template, out IntPtr e);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmFilterEnum0(IntPtr h, IntPtr e, uint n, out IntPtr entries, out uint returned);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmFilterDestroyEnumHandle0(IntPtr h, IntPtr e);
  [DllImport("fwpuclnt.dll")] static extern void FwpmFreeMemory0(ref IntPtr p);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmFilterDeleteByKey0(IntPtr h, ref Guid k);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmSubLayerDeleteByKey0(IntPtr h, ref Guid k);
  [DllImport("fwpuclnt.dll")] static extern uint FwpmProviderDeleteByKey0(IntPtr h, ref Guid k);
  public static string Run() {
    string[] sub = new string[] { "c971a69f-d6ab-4885-9b49-506d8aa51c86", "3e29ae7e-fd9f-413a-8b8d-da9bd3a96359", "6cf901ba-a6cd-4846-81a5-2598c55bdef5" };
    SESSION se = new SESSION(); IntPtr h; uint rc = FwpmEngineOpen0(null, 0xFFFFFFFF, IntPtr.Zero, ref se, out h);
    if (rc != 0) return "engine open failed 0x" + rc.ToString("X8");
    string r = ""; List<Guid> del = new List<Guid>(); IntPtr en;
    rc = FwpmFilterCreateEnumHandle0(h, IntPtr.Zero, out en);
    if (rc != 0) { FwpmEngineClose0(h); return "enumeration failed 0x" + rc.ToString("X8"); }
    while (true) {
      IntPtr entries; uint n; rc = FwpmFilterEnum0(h, en, 100, out entries, out n);
      if (rc != 0) { r += "enumeration error 0x" + rc.ToString("X8") + "\n"; break; }
      if (n == 0) { FwpmFreeMemory0(ref entries); break; }
      for (int i = 0; i < n; i++) {
        IntPtr p = Marshal.ReadIntPtr(entries, i * IntPtr.Size); FILTER f = (FILTER)Marshal.PtrToStructure(p, typeof(FILTER));
        string name = f.displayData.n == IntPtr.Zero ? "" : Marshal.PtrToStringUni(f.displayData.n); string sl = f.subLayerKey.ToString();
        if (Array.IndexOf(sub, sl) >= 0) del.Add(f.filterKey);
        else if (name.IndexOf("srt-win", StringComparison.OrdinalIgnoreCase) >= 0 || name.IndexOf("BlarAI #1763", StringComparison.OrdinalIgnoreCase) >= 0) r += "foreign " + f.filterKey + " " + sl + " " + name + "\n";
      }
      FwpmFreeMemory0(ref entries);
    }
    FwpmFilterDestroyEnumHandle0(h, en);
    foreach (Guid g in del) { Guid k = g; r += "filter " + k + " 0x" + FwpmFilterDeleteByKey0(h, ref k).ToString("X8") + "\n"; }
    foreach (string s in sub) { Guid k = new Guid(s); r += "sublayer " + s + " 0x" + FwpmSubLayerDeleteByKey0(h, ref k).ToString("X8") + "\n"; }
    Guid pk = new Guid("3e29ae7e-fd9f-413a-8b8d-da9bd3a96360"); r += "provider " + pk + " 0x" + FwpmProviderDeleteByKey0(h, ref pk).ToString("X8") + "\n";
    FwpmEngineClose0(h); return r;
  }
}
"@
[ManualNep5Rollback]::Run()   # 0x00000000 = deleted; 0x80320003/05/07 = was already gone. "foreign" lines are reported, never deleted. Then: netsh wfp show filters file=check.xml and search it for "BlarAI #1763", "srt-win" and the three sublayer GUIDs.
'@

function ConvertFrom-ManualN5Output {
    # PURE. The text ManualNep5Rollback.Run() returns. Ok only when the engine was opened and enumerated, no "foreign" line was reported, the three sublayer rows and
    # the provider row are present, and every status is 0 (deleted) or a not-found status (already gone). Filter rows may be any number (including none).
    param([string]$Text)
    $rows = @(); $foreign = @(); $bad = @()
    foreach ($l in ($Text -split "`r?`n")) {
        if ($l -match '^(filter|sublayer|provider)\s+([0-9a-fA-F-]{36})\s+0x([0-9A-Fa-f]{8})\s*$') {
            $st = [uint32]('0x' + $Matches[3])
            $good = ($st -eq 0 -or $st -in @([uint32]2150760451, [uint32]2150760453, [uint32]2150760455, [uint32]2150760456))
            $rows += [ordered]@{ kind = $Matches[1]; key = $Matches[2].ToLowerInvariant(); status = ('0x' + $Matches[3].ToUpper()); ok = $good }
        } elseif ($l -match '^foreign\s') { $foreign += $l.Trim() }
        elseif ($l.Trim()) { $bad += $l.Trim() }
    }
    $subs = @($rows | Where-Object { $_.kind -eq 'sublayer' }); $prov = @($rows | Where-Object { $_.kind -eq 'provider' })
    $okAll = ($bad.Count -eq 0 -and $foreign.Count -eq 0 -and $subs.Count -eq 3 -and $prov.Count -eq 1 -and @($rows | Where-Object { -not $_.ok }).Count -eq 0)
    $why = if ($okAll) { 'every filter under S1/S2/S3, the three sublayers and the provider deleted or already gone' }
           elseif ($bad.Count) { "unrecognised output (engine open or enumeration failed?): $($bad -join ' | ')" }
           elseif ($foreign.Count) { "a filter of ours or srt-win's sits outside S1/S2/S3 (reported, not deleted): $($foreign -join ' | ')" }
           elseif ($subs.Count -ne 3 -or $prov.Count -ne 1) { 'expected three sublayer rows and one provider row' }
           else { 'a delete returned an error status' }
    return [ordered]@{ Ok = $okAll; Rows = $rows; Foreign = $foreign; Reason = $why }
}

function Invoke-ManualN5Rollback {
    # Compiles the self-contained snippet and runs it (elevated, 64-bit). It reads nothing from disk but this library's own text, so it still works when the harness is missing,
    # untrusted or broken. It cannot read the state back; the statuses it prints are its evidence, and the caller then reads the sublayers and the provider by key.
    if (-not [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { return [ordered]@{ Ok = $false; Rows = @(); Foreign = @(); Reason = 'not elevated' } }
    try {
        $cs = [regex]::Match($script:N5ManualRollbackSnippet, '(?s)@"\r?\n(.*?)\r?\n"@').Groups[1].Value
        if (-not ('ManualNep5Rollback' -as [type])) { Add-Type -TypeDefinition $cs -Language CSharp }
        return (ConvertFrom-ManualN5Output -Text ([ManualNep5Rollback]::Run()))
    } catch { return [ordered]@{ Ok = $false; Rows = @(); Foreign = @(); Reason = "manual rollback failed: $($_.Exception.Message). Windows PowerShell 5.1 writes the compiled snippet to a DLL under %TEMP% and endpoint protection on the development machine refused to load this one: run the snippet from PowerShell 7 (pwsh), which compiles it in memory." } }
}

# ---- the harness contract: what this side may ask `halfset` and how it reads the answer ---------------------------------------------
function Test-HalfsetArgv {
    # PURE. Allowlist over the argument vector, in front of every harness run: a known verb, only that verb's options, a sublayer that is S1, S2 or S3, a SID that
    # is one of the two test SIDs, a plain GUID key. Returns @{ Ok; Class = sublayer|sid|syntax|''; Reason }. Class 'sublayer' is a STOP (exit 9), 'sid' is exit 3.
    param([string[]]$Argv)
    $fail = { param($c, $r) return [ordered]@{ Ok = $false; Class = $c; Reason = $r } }
    $a = @($Argv)
    if ($a.Count -eq 0) { return (& $fail 'syntax' 'empty argument vector') }
    $verb = $a[0]
    if ($script:N5HarnessVerbs -notcontains $verb) { return (& $fail 'syntax' "verb '$verb' is not on the allowlist") }
    $opts = @{}; $flags = @{}; $i = 1
    while ($i -lt $a.Count) {
        $t = $a[$i]
        if ($t -eq '--all-ours') { $flags['all-ours'] = $true; $i++; continue }
        if ($t -in @('--sublayer', '--sid', '--key', '--range')) {
            if ($i + 1 -ge $a.Count) { return (& $fail 'syntax' "option $t has no value") }
            if ($opts.ContainsKey($t)) { return (& $fail 'syntax' "option $t given twice") }
            $opts[$t] = [string]$a[$i + 1]; $i += 2; continue
        }
        return (& $fail 'syntax' "unexpected token '$t'")
    }
    $allowedOpts = switch ($verb) {
        'install' { @('--sublayer', '--sid', '--range') } 'status' { @('--sublayer') } 'enum' { @('--sublayer') } 'delete-filter' { @('--sublayer', '--key') }
        'delete-sublayer' { @('--sublayer') } 'uninstall' { @('--sublayer') } default { @() }
    }
    foreach ($o in $opts.Keys) { if ($allowedOpts -notcontains $o) { return (& $fail 'syntax' "$o is not an option of $verb") } }
    if ($flags['all-ours'] -and $verb -ne 'enum') { return (& $fail 'syntax' '--all-ours belongs to enum only') }
    if ($flags['all-ours'] -and $opts.ContainsKey('--sublayer')) { return (& $fail 'syntax' '--all-ours takes no --sublayer') }
    $needSub = ($verb -in @('install', 'status', 'delete-filter', 'delete-sublayer', 'uninstall')) -or ($verb -eq 'enum' -and -not $flags['all-ours'])
    if ($needSub) {
        if (-not $opts.ContainsKey('--sublayer')) { return (& $fail 'syntax' "$verb needs --sublayer") }
        if (-not (Get-N5SubLayerId $opts['--sublayer'])) { return (& $fail 'sublayer' "sublayer '$($opts['--sublayer'])' is not S1, S2 or S3: STOP") }
        if ($opts['--sublayer'] -cne (ConvertTo-N5Guid $opts['--sublayer'])) { return (& $fail 'syntax' 'the sublayer must be written as a lowercase plain GUID') }
    }
    if ($verb -eq 'install') {
        if (-not $opts.ContainsKey('--sid')) { return (& $fail 'syntax' 'install needs --sid') }
        if ($opts['--sid'] -ne $script:N5SpikeSid -and $opts['--sid'] -ne $script:N5StaleSid) { return (& $fail 'sid' "SID '$($opts['--sid'])' is not blarai-spike's or the stale test SID") }
        if ($opts.ContainsKey('--range') -and $opts['--range'] -notmatch '^\d{4,5}-\d{4,5}$') { return (& $fail 'syntax' 'the range must be LOW-HIGH') }
    }
    if ($verb -eq 'delete-filter') {
        if (-not $opts.ContainsKey('--key')) { return (& $fail 'syntax' 'delete-filter needs --key') }
        if ($opts['--key'] -cnotmatch '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$') { return (& $fail 'syntax' "the key '$($opts['--key'])' is not a lowercase plain GUID") }
    }
    return [ordered]@{ Ok = $true; Class = ''; Reason = '' }
}

function Invoke-Halfset {
    # Validates the vector (Test-HalfsetArgv), runs it through the Runner, parses the ONE JSON object on stdout. Never throws on a failed run.
    # Returns @{ Refused; Class; Reason; Argv; ExitCode; Outcome; Json; Stdout; Stderr; TimedOut; At }. A refused vector is never handed to the Runner.
    param([Parameter(Mandatory)][scriptblock]$Runner, [Parameter(Mandatory)][string[]]$Argv, [scriptblock]$ArgvValidator = { param($v) Test-HalfsetArgv -Argv $v })
    $at = Get-N5Now
    $v = & $ArgvValidator $Argv
    if (-not $v.Ok) {
        $rec = [pscustomobject]@{ Refused = $true; Class = $v.Class; Reason = $v.Reason; Argv = @($Argv); ExitCode = $null; Outcome = 'refused_before_run'; Json = $null; Stdout = ''; Stderr = ''; TimedOut = $false; At = $at }
        if ($null -ne $script:N5CommandLog) { [void]$script:N5CommandLog.Add([ordered]@{ at = $at; argv = @($Argv); refused = $true; reason = $v.Reason }) }
        return $rec
    }
    $r = $null; $argvRun = @($Argv)
    if ($script:N5MutatingVerbs -contains $Argv[0] -and $script:N5LiveProof) { $argvRun = @($Argv) + @('--live', [string]$script:N5LiveProof) }
    try { $r = & $Runner @($argvRun) } catch { $r = [pscustomobject]@{ ExitCode = -2; Stdout = ''; Stderr = "runner threw: $($_.Exception.Message)"; TimedOut = $false } }
    $json = $null; $so = [string]$r.Stdout
    if ($so.Trim()) { try { $json = ConvertFrom-Json -InputObject $so.Trim() } catch { $json = $null } }
    $code = $r.ExitCode
    $outcome = if ($null -eq $code) { 'no_exit_code' } elseif ($script:N5HarnessExit.ContainsKey([int]$code)) { $script:N5HarnessExit[[int]$code] } else { "unknown_exit_$code" }
    if ($r.TimedOut) { $outcome = 'timed_out' }
    $rec = [pscustomobject]@{ Refused = $false; Class = ''; Reason = ''; Argv = @($argvRun); ExitCode = $code; Outcome = $outcome; Json = $json; Stdout = $so; Stderr = [string]$r.Stderr; TimedOut = [bool]$r.TimedOut; At = $at }
    if ($null -ne $script:N5CommandLog) { [void]$script:N5CommandLog.Add([ordered]@{ at = $at; argv = @($argvRun); exit = $code; outcome = $outcome; stdout = $so; stderr = [string]$r.Stderr }) }
    return $rec
}

function ConvertTo-N5Layer {
    # PURE. 'v4' | 'v6' | 'other' from the harness's layer text (ale_auth_connect_v4/v6 or the layer GUID).
    param($Layer)
    $s = ([string]$Layer).ToLowerInvariant().Trim('{', '}')
    if ($s -eq 'ale_auth_connect_v4' -or $s -eq $script:N5LayerV4) { return 'v4' }
    if ($s -eq 'ale_auth_connect_v6' -or $s -eq $script:N5LayerV6) { return 'v6' }
    return 'other'
}

function ConvertFrom-HarnessFilters {
    # PURE. The `filters` array of an `enum` result as rows: Key, SubLayer (lowercase GUID), Layer, Name, Kind, Tool, Sid, HasUser. @{ Ok; Rows; Problem }.
    # Anything that is not a clear list is Ok = $false: an unreadable answer is never "zero filters".
    param($Json, [string]$Property = 'filters')
    if ($null -eq $Json) { return [ordered]@{ Ok = $false; Rows = @(); Problem = 'no JSON object' } }
    if (-not $Json.PSObject.Properties[$Property]) { return [ordered]@{ Ok = $false; Rows = @(); Problem = "no '$Property' member" } }
    $rows = @()
    foreach ($f in @($Json.$Property)) {
        if ($null -eq $f) { continue }
        $k = ConvertTo-N5Guid $f.key; $s = ConvertTo-N5Guid $f.sublayer
        if (-not $k -or -not $s) { return [ordered]@{ Ok = $false; Rows = @(); Problem = 'a filter row has no readable key or sublayer' } }
        $rows += [pscustomobject]@{ Key = $k; SubLayer = $s; Layer = (ConvertTo-N5Layer $f.layer); Name = [string]$f.name; Kind = [string]$f.kind; Tool = [string]$f.tool; Sid = [string]$f.user_sid; HasUser = [bool]$f.has_user_condition; Action = [string]$f.action }
    }
    if ($Json.PSObject.Properties['count'] -and $Property -eq 'filters' -and [int]$Json.count -ne $rows.Count) { return [ordered]@{ Ok = $false; Rows = @(); Problem = "count $($Json.count) does not equal the $($rows.Count) rows listed" } }
    return [ordered]@{ Ok = $true; Rows = $rows; Problem = '' }
}

function Get-SrtRole {
    # PURE. block-v4 | block-v6 | permit-v4 | permit-v6 | other, from the srt-win tag kind (block-user / permit-loopback-user) and the layer.
    param($Row)
    $fam = $Row.Layer
    if ($fam -notin @('v4', 'v6')) { $fam = if ($Row.Name -match 'srt-win-v4-') { 'v4' } elseif ($Row.Name -match 'srt-win-v6-') { 'v6' } else { 'other' } }
    if ($fam -eq 'other') { return 'other' }
    if ($Row.Kind -eq 'block-user') { return "block-$fam" }
    if ($Row.Kind -eq 'permit-loopback-user') { return "permit-$fam" }
    return 'other'
}

function Get-SrtStatusWord {
    # PURE. installed | absent | cannot-read | unparsed, from a `status` result (the harness prints srt-win's own JSON under srt_win_status).
    param($Json)
    if ($null -eq $Json -or -not $Json.PSObject.Properties['srt_win_status'] -or $null -eq $Json.srt_win_status) { return 'unparsed' }
    $st = $Json.srt_win_status
    $w = ''
    foreach ($p in 'state', 'status') { if ($st.PSObject.Properties[$p]) { $w = [string]$st.$p; break } }
    if ($w -in @('installed', 'absent', 'cannot-read')) { return $w }
    return 'unparsed'
}

function Get-HarnessFailureClass {
    # PURE. How a failed harness run is to be treated: stop (a foreign filter: exit 9), unsafe (a SID refusal), denied (engine said no), unreadable, other.
    param($Run)
    if ($Run.Refused) { return $(if ($Run.Class -eq 'sublayer') { 'stop' } elseif ($Run.Class -eq 'sid') { 'unsafe' } else { 'other' }) }
    switch ($Run.ExitCode) { 0 { return 'ok' } 9 { return 'stop' } 4 { return 'unsafe' } 3 { return 'stop' } 7 { return 'denied' } 6 { return 'unreadable' } 12 { return 'not_armed' } 13 { return 'trace_failed' } default { return 'other' } }
}

function Get-N5RawSha256 {
    # SHA-256 of a file's bytes as they are (exe, Rust source and Cargo.lock are hashed raw; only the scripts are LF-normalised). $null when unreadable.
    param([Parameter(Mandatory)][string]$Path)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))) -replace '-', '' } finally { $sha.Dispose() }
    } catch { return $null }
}

function New-HalfsetRunner {
    # The real Runner. The exe's raw SHA-256 is compared with the one the proof bound BEFORE every run (a changed exe is refused: ExitCode -1). Starts the process
    # hidden, reads stdout/stderr, kills it past TimeoutSec. $TracePath, when given, is handed to the harness as HALFSET_ENGINE_OPEN_TRACE.
    param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$ExpectedSha256, [int]$TimeoutSec = 180, [string]$TracePath)
    $exeC = $Exe; $shaC = $ExpectedSha256.ToUpperInvariant(); $toC = $TimeoutSec; $trC = $TracePath
    return {
        param([string[]]$Argv)
        $now = Get-N5RawSha256 -Path $exeC
        if (-not $now -or $now -ne $shaC) { return [pscustomobject]@{ ExitCode = -1; Stdout = ''; Stderr = "harness exe hash is $now, not the proof's ${shaC}: refusing to run it"; TimedOut = $false } }
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName = $exeC; $psi.Arguments = (@($Argv) -join ' '); $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
        if ($trC) { $psi.EnvironmentVariables['HALFSET_ENGINE_OPEN_TRACE'] = $trC }
        $p = New-Object Diagnostics.Process; $p.StartInfo = $psi
        [void]$p.Start()
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit($toC * 1000)) { try { $p.Kill() } catch {}; return [pscustomobject]@{ ExitCode = -3; Stdout = ''; Stderr = "harness did not finish within $toC s"; TimedOut = $true } }
        $p.WaitForExit()
        return [pscustomobject]@{ ExitCode = $p.ExitCode; Stdout = $so.Result; Stderr = $se.Result; TimedOut = $false }
    }.GetNewClosure()
}

# ---- SID allowlist (reuses the arms' SID-safety function through Get-SafeSidProblems' inputs) ----------------------------------------------
function Get-Nep5SidProblems {
    # PURE on its arguments. Empty = the SID may key a filter. Only blarai-spike's SID (which must be what the account resolves to) or the stale test SID (which
    # must NOT resolve) is accepted; then the arms' own safety function refuses the operator's SID and any group in his token. $Resolve { param($which) } answers
    # 'spike' with the account's SID text (or $null) and 'stale' with the account the stale SID resolves to (or $null).
    param([string]$Sid, [string]$OperatorSid, [string[]]$OperatorGroups = @(), [scriptblock]$Resolve)
    $p = New-Object System.Collections.ArrayList
    if ($Sid -ne $script:N5SpikeSid -and $Sid -ne $script:N5StaleSid) { [void]$p.Add("SID '$Sid' is neither blarai-spike's nor the stale test SID"); return @($p) }
    if ($Sid -eq $script:N5SpikeSid) {
        $r = if ($Resolve) { & $Resolve 'spike' } else { $null }
        if ($r -ne $script:N5SpikeSid) { [void]$p.Add("the account blarai-spike does not resolve to the recorded SID (got '$r')") }
    } else {
        $r = if ($Resolve) { & $Resolve 'stale' } else { 'unknown' }
        if ($r) { [void]$p.Add("the stale test SID resolves to '$r' on this machine: it must not") }
    }
    foreach ($m in @(Test-CoderSidSafe $Sid $OperatorSid $OperatorGroups)) { [void]$p.Add($m) }
    return @($p)
}

function New-Nep5SidResolver {
    # The real resolver: LookupAccountName for the spike account, LookupAccountSid (Translate) for the stale SID.
    return {
        param($which)
        if ($which -eq 'spike') { try { return (Get-LocalUser -Name $script:SpikeUser -ErrorAction Stop).SID.Value } catch { return $null } }
        try { return ((New-Object Security.Principal.SecurityIdentifier $script:N5StaleSid).Translate([Security.Principal.NTAccount])).Value } catch { return $null }
    }
}

# ---- plans: the objects of each of our rows, as plain descriptors (the real backend converts them to C#) ---------------------------------
function New-N5FilterDescriptor {
    param([string]$Id, [string]$SubLayer, [bool]$V6, [bool]$Permit, [string]$Sid, [bool]$UseProvider, [bool]$HasRemote = $false, [int]$RemotePort = 0, [bool]$Attempt = $false)
    return [pscustomobject]@{ Id = $Id; Key = $script:N5FilterKeys[$Id]; Name = "$($script:N5Marker) $Id"; SubLayer = $SubLayer; V6 = $V6; Permit = $Permit; UserSid = $Sid; UseProvider = $UseProvider
                              HasRemote = $HasRemote; RemoteAddr = $(if ($HasRemote) { [uint32]2130706433 } else { [uint32]0 }); RemotePort = $RemotePort; Attempt = $Attempt
                              Weight = $(if ($Permit) { $script:N5PermitWeight } else { $script:N5BlockWeight }) }
}

function Get-Nep5OurPlan {
    # PURE. The descriptor of one of our rows: o1 (V4 block only), o2 (V6 block only), o3 (permit without a block), o4 (both blocks + an exact-port permit on
    # 127.0.0.1:<PortOut>, no user condition), o5 (a block with no provider attempted, in a sublayer that has one), o6 (a filter naming a missing sublayer),
    # r7 (S3: unlabelled blocks for the account). Provider/AddSubLayer say what the set transaction adds; Attempts are added one by one and their status is the result.
    param([Parameter(Mandatory)][string]$Id, [string]$Sid = $script:N5SpikeSid)
    $s2 = $script:N5SubLayers.S2; $s3 = $script:N5SubLayers.S3; $F = { param($i, $sl, $v6, $perm, $sid, $up, $rem = $false, $port = 0, $att = $false) New-N5FilterDescriptor -Id $i -SubLayer $sl -V6 $v6 -Permit $perm -Sid $sid -UseProvider $up -HasRemote $rem -RemotePort $port -Attempt $att }
    $plan = [ordered]@{ Id = $Id; Provider = $true; SubLayer = $s2; SubLayerUsesProvider = $true; Filters = @(); Attempts = @() }
    switch ($Id) {
        'o1' { $plan.Filters = @(& $F 's2-block-v4' $s2 $false $false $Sid $true) }
        'o2' { $plan.Filters = @(& $F 's2-block-v6' $s2 $true $false $Sid $true) }
        'o3' { $plan.Filters = @(& $F 's2-permit-v4' $s2 $false $true $Sid $true) }
        'o4' { $plan.Filters = @((& $F 's2-block-v4' $s2 $false $false $Sid $true), (& $F 's2-block-v6' $s2 $true $false $Sid $true), (& $F 's2-exactport-permit-v4' $s2 $false $true $null $true $true $script:N5PortOut)) }
        'o5' { $plan.Attempts = @(& $F 's2-noprov-block-v4' $s2 $false $false $Sid $false) }
        'o6' { $plan.Provider = $false; $plan.SubLayer = $null; $plan.SubLayerUsesProvider = $false; $plan.Attempts = @(& $F 's2-missing-sublayer-v4' $script:N5MissingSubLayer $false $false $Sid $false $false 0 $true) }
        'r7' { $plan.SubLayer = $s3; $plan.Filters = @((& $F 's3-block-v4' $s3 $false $false $Sid $true), (& $F 's3-block-v6' $s3 $true $false $Sid $true)) }
        default { throw "unknown plan '$Id'" }
    }
    $plan.Filters = @($plan.Filters); $plan.Attempts = @($plan.Attempts)
    return [pscustomobject]$plan
}

function Get-Nep5PlanProblems {
    # PURE. Everything the add path checks about a plan before any engine call: every sublayer in the allowlist (an attempt may also name the one recorded missing
    # sublayer, never anything else), every SID allowed, every name carries the marker, a block always carries the user condition, no filter without a condition.
    param([Parameter(Mandatory)]$Plan)
    $p = New-Object System.Collections.ArrayList
    if ($Plan.SubLayer -and -not (Get-N5SubLayerId $Plan.SubLayer)) { [void]$p.Add("plan sublayer $($Plan.SubLayer) is not S1, S2 or S3") }
    foreach ($f in @($Plan.Filters) + @($Plan.Attempts)) {
        if (-not $f) { continue }
        $isMissing = ((ConvertTo-N5Guid $f.SubLayer) -eq $script:N5MissingSubLayer)
        if ($f.Attempt) { if (-not $isMissing -and -not (Get-N5SubLayerId $f.SubLayer)) { [void]$p.Add("$($f.Id): sublayer $($f.SubLayer) is not allowed") } }
        elseif (-not (Get-N5SubLayerId $f.SubLayer)) { [void]$p.Add("$($f.Id): sublayer $($f.SubLayer) is not S1, S2 or S3") }
        if ($isMissing -and -not $f.Attempt) { [void]$p.Add("$($f.Id): the missing sublayer may only be named by an attempt row") }
        if ($f.UserSid -and $f.UserSid -ne $script:N5SpikeSid -and $f.UserSid -ne $script:N5StaleSid) { [void]$p.Add("$($f.Id): SID $($f.UserSid) is not allowed") }
        if ($f.Name -notlike "$($script:N5Marker)*") { [void]$p.Add("$($f.Id): the display name lacks the marker") }
        if (-not $f.Permit -and -not $f.UserSid) { [void]$p.Add("$($f.Id): a block without the user condition could cut the operator off") }
        if (-not $f.UserSid -and -not $f.HasRemote) { [void]$p.Add("$($f.Id): no condition at all") }
    }
    return @($p)
}

function ConvertTo-N5Set {
    # The plan's set transaction as the C# type (the add-set part only: provider, sublayer, Filters). Needs Initialize-Nep5Type.
    param([Parameter(Mandatory)]$Plan)
    $s = New-Object BlarAI.Nep5.N5Set
    $s.AddProvider = [bool]$Plan.Provider; $s.AddSubLayer = [bool]$Plan.SubLayer; $s.SubLayerUsesProvider = [bool]$Plan.SubLayerUsesProvider
    if ($Plan.SubLayer) { $s.SubLayer = [guid]$Plan.SubLayer }
    foreach ($f in @($Plan.Filters)) { $s.Filters.Add((ConvertTo-N5Filter $f)) }
    return $s
}

function ConvertTo-N5Filter {
    param([Parameter(Mandatory)]$F)
    $c = New-Object BlarAI.Nep5.N5Filter
    $c.Key = [guid]$F.Key; $c.Name = [string]$F.Name; $c.V6 = [bool]$F.V6; $c.Permit = [bool]$F.Permit; if ($F.UserSid) { $c.UserSid = [string]$F.UserSid }
    $c.HasRemote = [bool]$F.HasRemote; $c.RemoteAddr = [uint32]$F.RemoteAddr; $c.RemotePort = [uint16]$F.RemotePort; $c.SubLayer = [guid]$F.SubLayer
    $c.UseProvider = [bool]$F.UseProvider; $c.AttemptMissing = [bool]($F.Attempt -and ((ConvertTo-N5Guid $F.SubLayer) -eq $script:N5MissingSubLayer)); $c.Weight = [uint64]$F.Weight
    return $c
}

# ---- backends -------------------------------------------------------------------------------------------------------------------------
function New-Nep5RealBackend {
    # Opens a NON-dynamic engine session. Requires Initialize-Nep5Type and an elevated 64-bit process. Reads and adds only objects of the plan; deletes by key.
    $eng = [BlarAI.Nep5.N5Engine]::Open('BlarAI #1763 open-questions matrix (non-dynamic session)')
    $be = [pscustomobject]@{ Kind = 'real'; Engine = $eng }
    $be | Add-Member -MemberType ScriptMethod -Name Flags -Value { param($kind, $key) [long]$this.Engine.Flags([string]$kind, [guid]$key) }
    $be | Add-Member -MemberType ScriptMethod -Name AddSet -Value { param($plan) @($this.Engine.AddSet((ConvertTo-N5Set $plan))) }
    $be | Add-Member -MemberType ScriptMethod -Name AddOne -Value { param($f) [string]$this.Engine.AddOne((ConvertTo-N5Filter $f)) }
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

function New-Nep5World {
    # The fake machine: filters (key -> row), sublayers (key -> provider key or ''), providers (key -> $true), plus an engine-open counter.
    return [pscustomobject]@{ Filters = @{}; SubLayers = @{}; Providers = @{}; EngineOpens = 0; Foreign = $false }
}

function New-Nep5FakeBackend {
    # An in-memory stand-in over a fake world, with switchable failures; used only by -SelfTest. It never touches WFP.
    #   FailAddAfter N   -> AddSet adds N objects (provider, sublayer, filters in that order) then throws: a half-failed, NON-atomic add
    #   FailDelete       keys whose Delete returns an error status
    #   Unreadable       -> Flags throws
    #   AddClearsFlags   -> AddSet "succeeds" but stores the objects without the persistent flag
    #   RefuseAttempt    -> AddOne returns the engine refusal for filters that name a missing sublayer or have no provider in a sublayer that has one (as the engine would)
    param([Parameter(Mandatory)]$World, [int]$FailAddAfter = -1, [string[]]$FailDelete = @(), [bool]$Unreadable = $false, [bool]$AddClearsFlags = $false, [bool]$RefuseAttempt = $true)
    $be = [pscustomobject]@{ Kind = 'fake'; World = $World; Calls = (New-Object System.Collections.ArrayList); FailAddAfter = $FailAddAfter; FailDelete = $FailDelete; Unreadable = $Unreadable; AddClearsFlags = $AddClearsFlags; RefuseAttempt = $RefuseAttempt }
    $be | Add-Member -MemberType ScriptMethod -Name Flags -Value {
        param($kind, $key)
        [void]$this.Calls.Add("flags $kind $key")
        if ($this.Unreadable) { throw 'fake engine unreadable' }
        $k = ConvertTo-N5Guid $key; $w = $this.World
        $store = switch ($kind) { 'filter' { $w.Filters } 'sublayer' { $w.SubLayers } 'provider' { $w.Providers } default { throw "bad kind $kind" } }
        if ($store.ContainsKey($k)) { [long]$(if ($this.AddClearsFlags) { 0 } else { 1 }) } else { [long]-1 }
    }
    $be | Add-Member -MemberType ScriptMethod -Name AddSet -Value {
        param($plan)
        [void]$this.Calls.Add('addset'); $w = $this.World; $n = 0
        $steps = @()
        if ($plan.Provider) { $steps += , @('provider', $script:N5ProviderKey) }
        if ($plan.SubLayer) { $steps += , @('sublayer', $plan.SubLayer) }
        foreach ($f in @($plan.Filters)) { $steps += , @('filter', $f) }
        foreach ($s in $steps) {
            if ($this.FailAddAfter -ge 0 -and $n -ge $this.FailAddAfter) { throw "fake add failure after $n object(s)" }
            if ($s[0] -eq 'provider') { $w.Providers[(ConvertTo-N5Guid $s[1])] = $true }
            elseif ($s[0] -eq 'sublayer') { $w.SubLayers[(ConvertTo-N5Guid $s[1])] = $(if ($plan.SubLayerUsesProvider) { $script:N5ProviderKey } else { '' }) }
            else { $f = $s[1]; $w.Filters[(ConvertTo-N5Guid $f.Key)] = [pscustomobject]@{ Key = (ConvertTo-N5Guid $f.Key); SubLayer = (ConvertTo-N5Guid $f.SubLayer); Layer = $(if ($f.V6) { 'v6' } else { 'v4' }); Name = $f.Name; Kind = ''; Tool = ''; Sid = [string]$f.UserSid; HasUser = [bool]$f.UserSid; Action = $(if ($f.Permit) { 'permit' } else { 'block' }); HasRemote = [bool]$f.HasRemote; RemotePort = [int]$f.RemotePort } }
            $n++
        }
        @(1..[Math]::Max(1, $n))
    }
    $be | Add-Member -MemberType ScriptMethod -Name AddOne -Value {
        param($f)
        [void]$this.Calls.Add("addone $($f.Key)"); $w = $this.World; $sl = ConvertTo-N5Guid $f.SubLayer
        if ($this.RefuseAttempt) {
            if (-not $w.SubLayers.ContainsKey($sl)) { return 'error: FwpmFilterAdd0 0x80320007' }
            if (-not $f.UseProvider -and $w.SubLayers[$sl]) { return 'error: FwpmFilterAdd0 0x8032002F' }
        }
        $w.Filters[(ConvertTo-N5Guid $f.Key)] = [pscustomobject]@{ Key = (ConvertTo-N5Guid $f.Key); SubLayer = $sl; Layer = $(if ($f.V6) { 'v6' } else { 'v4' }); Name = $f.Name; Kind = ''; Tool = ''; Sid = [string]$f.UserSid; HasUser = [bool]$f.UserSid; Action = $(if ($f.Permit) { 'permit' } else { 'block' }); HasRemote = [bool]$f.HasRemote; RemotePort = [int]$f.RemotePort }
        'added'
    }
    $be | Add-Member -MemberType ScriptMethod -Name Delete -Value {
        param($kind, $key)
        [void]$this.Calls.Add("delete $kind $key"); $w = $this.World; $k = ConvertTo-N5Guid $key
        if ($this.FailDelete -contains $k) { return 'error: 0x8032000A' }
        $store = switch ($kind) { 'filter' { $w.Filters } 'sublayer' { $w.SubLayers } 'provider' { $w.Providers } default { throw "bad kind $kind" } }
        if ($store.ContainsKey($k)) { $store.Remove($k); 'deleted' } else { 'not_found' }
    }
    $be | Add-Member -MemberType ScriptMethod -Name Close -Value { [void]$this.Calls.Add('close') }
    return $be
}

function Invoke-FakeHalfsetCall {
    # The fake harness's behaviour over one state object (kept in a function: a scriptblock closure cannot see $script: variables).
    param($S, [string[]]$Argv)
    $w = $S.World; $a = @($Argv); [void]$S.Calls.Add(($a -join ' '))
    $res = { param($code, $obj) [pscustomobject]@{ ExitCode = $code; Stdout = (ConvertTo-Json -InputObject $obj -Depth 8 -Compress); Stderr = ''; TimedOut = $false } }
    $opt = { param($n) $i = [array]::IndexOf($a, $n); if ($i -ge 0 -and $i + 1 -lt $a.Count) { $a[$i + 1] } else { $null } }
    $verb = $a[0]
    if ($verb -eq '--version') { return (& $res 0 ([ordered]@{ version = 'fake'; pinned_srt_win_sha = $script:N5PinnedSrtSha; pinned_cargo_lock_sha256 = $S.LockHash.ToLowerInvariant(); halfset_rs_sha256 = $S.RsHash.ToLowerInvariant(); toggle_build = $false })) }
    if ($verb -eq 'selftest-refusals') { return (& $res 0 ([ordered]@{ ok = $true; command = 'selftest-refusals'; total = 51; failed = 0; engine_opens = $w.EngineOpens; checks = @(); exit = 0 })) }
    $sub = & $opt '--sublayer'; $live = & $opt '--live'
    if ($live -and $verb -notin $script:N5MutatingVerbs) { return (& $res 2 ([ordered]@{ ok = $false; error = 'usage'; detail = '--live is not an option of this verb'; exit = 2 })) }
    if ($sub -and -not (Get-N5SubLayerId $sub)) { return (& $res 3 ([ordered]@{ ok = $false; error = 'refused'; guard = 'sublayer'; exit = 3 })) }
    if ($S.Unreadable -and $verb -in @('enum', 'status')) { return (& $res 6 ([ordered]@{ ok = $false; error = 'cannot_read'; exit = 6 })) }
    $row = { param($f) [ordered]@{ key = $f.Key; layer = $(if ($f.Layer -eq 'v6') { 'ale_auth_connect_v6' } else { 'ale_auth_connect_v4' }); sublayer = $f.SubLayer; name = $f.Name; tool = $f.Tool; kind = $f.Kind; user_sid = $f.Sid; port_range = $null; has_user_condition = $f.HasUser; action = $f.Action } }
    $inSub = { param($s) @($w.Filters.Values | Where-Object { $_.SubLayer -eq $s } | Sort-Object Key) }
    if ($verb -eq 'enum' -and $a -contains '--all-ours') {
        $mine = @($w.Filters.Values | Where-Object { (Get-N5SubLayerId $_.SubLayer) -or $_.Name -match 'srt-win' -or $_.Name -like "$($script:N5Marker)*" } | Sort-Object Key)
        $stops = @($mine | Where-Object { -not (Get-N5SubLayerId $_.SubLayer) })
        $code = $(if ($stops.Count) { 9 } else { 0 })
        return (& $res $code ([ordered]@{ ok = ($stops.Count -eq 0); command = 'enum_all_ours'; scanned = $w.Filters.Count; count = $mine.Count; stop_count = $stops.Count; filters = @($mine | ForEach-Object { & $row $_ }); stop_filters = @($stops | ForEach-Object { & $row $_ }); exit = $code }))
    }
    if ($verb -eq 'enum') {
        if ($S.GarbageEnum) { return [pscustomobject]@{ ExitCode = 0; Stdout = 'not json at all'; Stderr = ''; TimedOut = $false } }
        $here = @(& $inSub $sub)
        return (& $res 0 ([ordered]@{ ok = $true; command = 'enum'; sublayer = $sub; count = $here.Count; filters = @($here | ForEach-Object { & $row $_ }); exit = 0 }))
    }
    if ($verb -eq 'status') {
        $inst = @(& $inSub $sub | Where-Object { $_.Tool -eq 'srt-win' -and $_.Kind -eq 'block-user' }).Count -gt 0
        return (& $res 0 ([ordered]@{ ok = $true; srt_win_status = [ordered]@{ state = $(if ($inst) { 'installed' } else { 'absent' }) }; exit = 0 }))
    }
    # mutating verbs: the arming interlock (exit 12 without --live, before any engine touch), then the stop sweep (a foreign filter of ours or srt-win's refuses everything)
    if (-not $live -or $S.NotArmed) { return (& $res 12 ([ordered]@{ ok = $false; error = 'not_armed'; exit = 12 })) }
    $foreign = @($w.Filters.Values | Where-Object { ($_.Name -match 'srt-win' -or $_.Name -like "$($script:N5Marker)*") -and -not (Get-N5SubLayerId $_.SubLayer) })
    if ($foreign.Count) { return (& $res 9 ([ordered]@{ ok = $false; error = 'stop'; exit = 9 })) }
    if ($S.Denied) { return (& $res 7 ([ordered]@{ ok = $false; error = 'engine_denied'; phase = $verb; call = 'FwpmTransactionBegin0'; rc = '0x80320009'; elevated = $false; exit = 7 })) }
    if ($verb -eq 'install') {
        $sid = & $opt '--sid'
        if ($sid -eq $S.OperatorSid -or $S.OperatorGroups -contains $sid) { return (& $res 4 ([ordered]@{ ok = $false; error = 'refused'; guard = 'sid'; exit = 4 })) }
        if ($sid -ne $script:N5SpikeSid -and $sid -ne $script:N5StaleSid) { return (& $res 4 ([ordered]@{ ok = $false; error = 'refused'; guard = 'sid'; exit = 4 })) }
        if (@(& $inSub $sub).Count) { return (& $res 5 ([ordered]@{ ok = $false; error = 'refused'; guard = 'sublayer_not_empty'; exit = 5 })) }
        if ($S.FailInstall) { return (& $res 10 ([ordered]@{ ok = $false; error = 'engine_error'; exit = 10 })) }
        $w.SubLayers[$sub] = ''
        $n = 0
        foreach ($d in @(@('block-user', 'v4', 'block'), @('block-user', 'v6', 'block'), @('permit-loopback-user', 'v4', 'permit'), @('permit-loopback-user', 'v6', 'permit'))) {
            $n++; $key = ('b1763{0:x3}-0000-4d8e-9a31-{1}' -f $n, $sub.Substring(24, 12)).ToLowerInvariant()
            $w.Filters[$key] = [pscustomobject]@{ Key = $key; SubLayer = $sub; Layer = $d[1]; Name = "srt-win-$($d[1])-$($d[0])"; Kind = $d[0]; Tool = 'srt-win'; Sid = $sid; HasUser = $true; Action = $d[2] }
        }
        $code = $(if ($S.NoReadback) { 8 } else { 0 })
        return (& $res $code ([ordered]@{ ok = ($code -eq 0); command = 'install'; sublayer = $sub; sid = $sid; readback_count = 4; expected_count = 4; filters = @(& $inSub $sub | ForEach-Object { & $row $_ }); exit = $code }))
    }
    if ($verb -eq 'delete-filter') {
        $k = & $opt '--key'
        if (-not ($w.Filters.ContainsKey($k) -and $w.Filters[$k].SubLayer -eq $sub)) { return (& $res 11 ([ordered]@{ ok = $false; error = 'target_not_under_sublayer'; exit = 11 })) }
        if ($S.FailDeleteFilter -contains $k) { return (& $res 10 ([ordered]@{ ok = $false; error = 'engine_error'; exit = 10 })) }
        $w.Filters.Remove($k)
        return (& $res 0 ([ordered]@{ ok = $true; command = 'delete-filter'; key = $k; sublayer = $sub; absent_after = $true; exit = 0 }))
    }
    if ($verb -eq 'delete-sublayer' -or $verb -eq 'uninstall') {
        if ($verb -eq 'uninstall') { foreach ($f in @(& $inSub $sub | Where-Object { $_.Tool -eq 'srt-win' })) { $w.Filters.Remove($f.Key) } }
        if (@(& $inSub $sub).Count) { return (& $res 5 ([ordered]@{ ok = $false; error = 'refused'; guard = 'sublayer_not_empty'; exit = 5 })) }
        $was = $w.SubLayers.ContainsKey($sub); if ($was) { $w.SubLayers.Remove($sub) }
        return (& $res 0 ([ordered]@{ ok = $true; command = $verb; sublayer = $sub; already_absent = (-not $was); absent_after = $true; exit = 0 }))
    }
    return (& $res 2 ([ordered]@{ ok = $false; error = 'usage'; exit = 2 }))
}

function New-FakeHalfset {
    # A Runner over the same fake world, speaking the harness's JSON and exit codes. Switches:
    #   Unreadable   every read exits 6;  Denied   every mutating call exits 7 with a status code;  GarbageEnum   enum prints something that is not a list
    #   FailDeleteFilter keys whose delete-filter exits 10;  OperatorSid / OperatorGroups  what its SID guard refuses (the real harness reads its own token)
    #   NoReadback  install adds the filters but reports exit 8 (read-back mismatch)
    #   ForeignKey  a key of a filter that sits under an unlisted sublayer (the stop sweep)
    param([Parameter(Mandatory)]$World, [bool]$Unreadable = $false, [bool]$Denied = $false, [bool]$GarbageEnum = $false, [string[]]$FailDeleteFilter = @(), [string]$OperatorSid = 'S-1-5-21-1-2-3-1001', [string[]]$OperatorGroups = @(), [bool]$NoReadback = $false, [bool]$FailInstall = $false, [string]$LockHash = $script:N5PinnedCargoLockSha256, [string]$RsHash = ('AB' * 32), [bool]$NotArmed = $false)
    $st = [pscustomobject]@{ World = $World; Unreadable = $Unreadable; Denied = $Denied; GarbageEnum = $GarbageEnum; FailDeleteFilter = $FailDeleteFilter; OperatorSid = $OperatorSid; OperatorGroups = $OperatorGroups; NoReadback = $NoReadback; FailInstall = $FailInstall; Calls = (New-Object System.Collections.ArrayList); LockHash = $LockHash; RsHash = $RsHash; NotArmed = $NotArmed }
    $runner = { param([string[]]$Argv) Invoke-FakeHalfsetCall -S $st -Argv $Argv }.GetNewClosure()
    $runner | Add-Member -NotePropertyName State -NotePropertyValue $st -Force
    return $runner
}

function Get-FakeExportText {
    param($World, [string]$Extra)
    $lines = New-Object System.Collections.ArrayList
    foreach ($k in $World.Filters.Keys) { $r = $World.Filters[$k]; [void]$lines.Add("<item><filterKey>{$($r.Key)}</filterKey><displayData><name>$($r.Name)</name></displayData><subLayerKey>{$($r.SubLayer)}</subLayerKey></item>") }
    return ("<wfpdiag>" + ($lines -join '') + $Extra + "</wfpdiag>")
}

function New-Nep5FakeExporter {
    # A fake `netsh wfp show filters`: one item per FILTER of the fake world (name and GUIDs, the sublayer GUID as a reference on the filter), as the real export is shaped; a bare sublayer or
    # provider does not appear in it, so their absence rests on the key reads, not on the export.
    param([Parameter(Mandatory)]$World, [bool]$Fail = $false, [string]$Extra = '')
    $w = $World; $f = $Fail; $x = $Extra
    return {
        param($Label)
        if ($f) { return [ordered]@{ ok = $false; text = ''; error = 'fake export failed'; path = $null; sha256 = $null; bytes = 0 } }
        $t = Get-FakeExportText -World $w -Extra $x
        return [ordered]@{ ok = $true; text = $t; error = $null; path = "fake-$Label.xml"; sha256 = 'FAKE'; bytes = $t.Length }
    }.GetNewClosure()
}

# ---- export (read-only) and the direct sweep -------------------------------------------------------------------------------------------
function Get-N5ExportHits {
    # PURE. How many times the marker, srt-win's name, each sublayer GUID and the provider GUID occur in the export text (case-insensitive; GUIDs with or without braces).
    param([string]$Text)
    $c = { param($needle) if ($Text) { [regex]::Matches($Text, [regex]::Escape($needle), 'IgnoreCase').Count } else { 0 } }
    $h = [ordered]@{ marker = (& $c $script:N5Marker); srt_win = (& $c 'srt-win'); provider = (& $c $script:N5ProviderKey) }
    foreach ($id in $script:N5SubLayers.Keys) { $h[$id] = (& $c $script:N5SubLayers[$id]) }
    $h['total'] = [int](($h.Values | Measure-Object -Sum).Sum)
    return $h
}

function Invoke-Nep5Export {
    # `netsh wfp show filters file=<path>` (read-only; needs elevation). The summary is the hit counts above; the file is kept unless it was clean and $DropClean is set.
    param([Parameter(Mandatory)][string]$Label, [Parameter(Mandatory)][string]$Path, [switch]$DropClean)
    $rec = [ordered]@{ ok = $false; label = $Label; at = (Get-N5Now); path = $Path; bytes = 0; sha256 = $null; text = ''; error = $null; seconds = 0 }
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
        $rec.bytes = $bytes.Length; $rec.text = (Read-ExportText $bytes); $rec.ok = $true
        if ($DropClean -and (Get-N5ExportHits -Text $rec.text).total -eq 0) { Remove-Item -LiteralPath $Path -Force; $rec.path = $null }
    } catch { $rec.error = $_.Exception.Message }
    $rec.seconds = [Math]::Round($sw.Elapsed.TotalSeconds, 1)
    return $rec
}

function Get-Nep5Residue {
    # READ-ONLY. What is there right now, by direct reads: enumeration of S1/S2/S3 and of everything of ours or srt-win's (the harness), and each sublayer and our
    # provider by key (our own engine). @{ Readable; Problems; SubLayers = @{S1 = @{filter_keys; present}}; Total; Foreign (rows outside S1/S2/S3); ProviderPresent; Rows }.
    # -NoHarness (no trusted harness is available): enumeration is skipped and only the sublayers and the provider are read by key. A sublayer cannot be deleted while any
    # filter is in it, so "sublayer absent" still implies "no filter in it"; a foreign filter cannot be seen this way (the record says enumeration was skipped).
    param([scriptblock]$Runner, $Backend, [switch]$NoHarness)
    $problems = New-Object System.Collections.ArrayList; $per = [ordered]@{}; $rows = @(); $total = 0; $foreign = @(); $prov = $null
    if ($NoHarness -or -not $Runner) {
        foreach ($id in $script:N5SubLayers.Keys) {
            $present = $null
            if ($Backend) { try { $present = ([long]$Backend.Flags('sublayer', $script:N5SubLayers[$id]) -ge 0) } catch { [void]$problems.Add("$id presence unreadable: $($_.Exception.Message)") } } else { [void]$problems.Add("$id presence unreadable: no engine backend") }
            $per[$id] = [ordered]@{ filter_keys = @(); present = $present; readable = $true; enum_skipped = $true }
        }
        if ($Backend) { try { $prov = ([long]$Backend.Flags('provider', $script:N5ProviderKey) -ge 0) } catch { [void]$problems.Add("provider presence unreadable: $($_.Exception.Message)") } } else { [void]$problems.Add('provider presence unreadable: no engine backend') }
        return [ordered]@{ Readable = ($problems.Count -eq 0); Problems = @($problems); SubLayers = $per; Total = 0; Foreign = @(); ProviderPresent = $prov; Rows = @(); EnumSkipped = $true }
    }
    foreach ($id in $script:N5SubLayers.Keys) {
        $key = $script:N5SubLayers[$id]
        $r = Invoke-Halfset -Runner $Runner -Argv @('enum', '--sublayer', $key)
        $parsed = $(if ($r.ExitCode -eq 0) { ConvertFrom-HarnessFilters -Json $r.Json } else { [ordered]@{ Ok = $false; Rows = @(); Problem = "harness exit $($r.ExitCode) ($($r.Outcome))" } })
        $present = $null
        if ($Backend) { try { $present = ([long]$Backend.Flags('sublayer', $key) -ge 0) } catch { [void]$problems.Add("$id presence unreadable: $($_.Exception.Message)") } } else { [void]$problems.Add("$id presence unreadable: no engine backend") }
        if (-not $parsed.Ok) { [void]$problems.Add("enum $id unreadable: $($parsed.Problem)") }
        else { $rows += @($parsed.Rows); $total += @($parsed.Rows).Count }
        $per[$id] = [ordered]@{ filter_keys = @($parsed.Rows | ForEach-Object { $_.Key }); present = $present; readable = [bool]$parsed.Ok }
    }
    $ao = Invoke-Halfset -Runner $Runner -Argv @('enum', '--all-ours')
    $stopRows = @()
    if ($ao.ExitCode -in @(0, 9) -and $ao.Json) {
        $pm = ConvertFrom-HarnessFilters -Json $ao.Json
        $ps = ConvertFrom-HarnessFilters -Json $ao.Json -Property 'stop_filters'
        if (-not $pm.Ok -or -not $ps.Ok) { [void]$problems.Add("enum --all-ours unreadable: $($pm.Problem) $($ps.Problem)") }
        else {
            $stopRows = @($ps.Rows)
            foreach ($f in @($pm.Rows)) { if (-not (Get-N5SubLayerId $f.SubLayer)) { $stopRows += $f } }
            $stopRows = @($stopRows | Group-Object Key | ForEach-Object { $_.Group[0] })
            # a filter the all-ours sweep sees inside S1/S2/S3 but the per-sublayer enumeration did not list is a disagreement between two reads: unreadable
            $listed = @($rows | ForEach-Object { $_.Key })
            foreach ($f in @($pm.Rows)) { if ((Get-N5SubLayerId $f.SubLayer) -and $listed -notcontains $f.Key) { [void]$problems.Add("filter $($f.Key) is in the all-ours sweep but not in the per-sublayer enumeration") } }
        }
        if ($ao.ExitCode -eq 9 -and $stopRows.Count -eq 0) { [void]$problems.Add('the harness exited 9 (stop) but listed no stop filter') }
    } else { [void]$problems.Add("enum --all-ours unreadable: harness exit $($ao.ExitCode) ($($ao.Outcome))") }
    $foreign = @($stopRows)
    if ($Backend) { try { $prov = ([long]$Backend.Flags('provider', $script:N5ProviderKey) -ge 0) } catch { [void]$problems.Add("provider presence unreadable: $($_.Exception.Message)") } } else { [void]$problems.Add('provider presence unreadable: no engine backend') }
    return [ordered]@{ Readable = ($problems.Count -eq 0); Problems = @($problems); SubLayers = $per; Total = $total; Foreign = $foreign; ProviderPresent = $prov; Rows = $rows }
}

function Invoke-Nep5DirectSweep {
    # The direct checks of the gate's section 6, as one record. Clean ONLY when: each of S1, S2, S3 enumerates to zero filters AND is absent; our provider is absent; the
    # `netsh wfp show filters` export has 0 hits for the marker, for srt-win's name, for the three sublayer GUIDs and for the provider GUID; nothing was unreadable.
    # Stop = a filter of ours or srt-win's outside S1/S2/S3 (exit 9, never cleaned up here). $AllowedSubLayers is the stop detector's allowlist (a test switches it wide
    # to show the stop then fails to fire).
    param([scriptblock]$Runner, $Backend, [Parameter(Mandatory)][scriptblock]$Exporter, [string]$Label = 'sweep', [string[]]$AllowedSubLayers, [switch]$NoHarness)
    $res = Get-Nep5Residue -Runner $Runner -Backend $Backend -NoHarness:$NoHarness
    $problems = New-Object System.Collections.ArrayList; foreach ($p in $res.Problems) { [void]$problems.Add($p) }
    $stop = $false
    $foreign = @($res.Foreign)
    if ($AllowedSubLayers) { $foreign = @($foreign | Where-Object { $AllowedSubLayers -notcontains $_.SubLayer }) }
    if ($foreign.Count) { $stop = $true; [void]$problems.Add("STOP: $($foreign.Count) filter(s) of ours or srt-win's outside S1/S2/S3: $(@($foreign | ForEach-Object { "$($_.Key)@$($_.SubLayer)" }) -join ', ')") }
    $notClean = New-Object System.Collections.ArrayList
    foreach ($id in $res.SubLayers.Keys) {
        $s = $res.SubLayers[$id]
        if ($s.readable -and $s.filter_keys.Count -gt 0) { [void]$notClean.Add("$id still holds $($s.filter_keys.Count) filter(s)") }
        if ($s.present -eq $true) { [void]$notClean.Add("$id sublayer is still present") }
    }
    if ($res.ProviderPresent -eq $true) { [void]$notClean.Add('our provider is still present') }
    $ex = $null; $hits = $null
    try { $ex = & $Exporter $Label } catch { $ex = [ordered]@{ ok = $false; text = ''; error = $_.Exception.Message } }
    if (-not $ex.ok) { [void]$problems.Add("export unreadable: $($ex.error)") }
    else {
        $hits = Get-N5ExportHits -Text $ex.text
        foreach ($k in @('marker', 'srt_win', 'S1', 'S2', 'S3', 'provider')) { if ($hits[$k] -gt 0) { [void]$notClean.Add("the export has $($hits[$k]) hit(s) for $k") } }
    }
    $unreadable = (@($problems | Where-Object { $_ -notlike 'STOP:*' }).Count -gt 0)
    $clean = ((-not $stop) -and (-not $unreadable) -and $notClean.Count -eq 0)
    return [ordered]@{ Label = $Label; At = (Get-N5Now); Clean = $clean; Stop = $stop; Unreadable = [bool]$unreadable; NotClean = @($notClean); Problems = @($problems); SubLayers = $res.SubLayers; ProviderPresent = $res.ProviderPresent; Foreign = $foreign
                       Export = [ordered]@{ ok = [bool]$ex.ok; path = $ex.path; sha256 = $ex.sha256; bytes = $ex.bytes; hits = $hits; error = $ex.error } }
}

# ---- removal by key --------------------------------------------------------------------------------------------------------------------
function Remove-Nep5All {
    # Removal BY KEY of everything in S1/S2/S3 and our provider, built for a set that is whole, half-added, or already gone. Order: every enumerated filter (harness
    # delete-filter; our own engine by key when the harness fails), our own fixed filter keys (idempotent safety net), each sublayer (harness delete-sublayer, then our
    # own engine), the provider. Every key is attempted whatever happened to the one before. A filter outside S1/S2/S3 is NEVER deleted here. The verdict is a direct
    # re-read (Get-Nep5Residue): Ok only when it is readable and empty.
    param([Parameter(Mandatory)][scriptblock]$Runner, $Backend)
    $steps = New-Object System.Collections.ArrayList
    $rec = { param($step, $via, $key, $st) [void]$steps.Add([ordered]@{ step = $step; via = $via; key = $key; status = $st }) }
    $before = Get-Nep5Residue -Runner $Runner -Backend $Backend
    foreach ($id in $script:N5SubLayers.Keys) {
        $skey = $script:N5SubLayers[$id]
        foreach ($k in @($before.SubLayers[$id].filter_keys)) {
            $r = Invoke-Halfset -Runner $Runner -Argv @('delete-filter', '--sublayer', $skey, '--key', $k)
            if ($r.ExitCode -eq 0) { & $rec 'filter' 'harness' $k 'deleted'; continue }
            $st = 'error: no backend'
            if ($Backend) { try { $st = [string]$Backend.Delete('filter', $k) } catch { $st = "error: $($_.Exception.Message)" } }
            & $rec 'filter' "harness-failed($($r.Outcome)); engine" $k $st
        }
    }
    if ($Backend) {
        foreach ($id in $script:N5FilterKeys.Keys) {
            $k = $script:N5FilterKeys[$id]; $st = 'error: not attempted'
            try { $st = [string]$Backend.Delete('filter', $k) } catch { $st = "error: $($_.Exception.Message)" }
            & $rec 'filter' 'engine-fixed-key' $k $st
        }
    }
    foreach ($id in $script:N5SubLayers.Keys) {
        $skey = $script:N5SubLayers[$id]
        $r = Invoke-Halfset -Runner $Runner -Argv @('delete-sublayer', '--sublayer', $skey)
        if ($r.ExitCode -eq 0) { & $rec 'sublayer' 'harness' $skey 'deleted'; continue }
        $st = 'error: no backend'
        if ($Backend) { try { $st = [string]$Backend.Delete('sublayer', $skey) } catch { $st = "error: $($_.Exception.Message)" } }
        & $rec 'sublayer' "harness-failed($($r.Outcome)); engine" $skey $st
    }
    $pst = 'error: no backend'
    if ($Backend) { try { $pst = [string]$Backend.Delete('provider', $script:N5ProviderKey) } catch { $pst = "error: $($_.Exception.Message)" } }
    & $rec 'provider' 'engine' $script:N5ProviderKey $pst
    $after = Get-Nep5Residue -Runner $Runner -Backend $Backend
    $empty = ($after.Readable -and $after.Total -eq 0 -and $after.Foreign.Count -eq 0 -and $after.ProviderPresent -eq $false -and @($after.SubLayers.Values | Where-Object { $_.present -ne $false }).Count -eq 0)
    $errs = @($steps | Where-Object { $_.status -like 'error*' })
    return [ordered]@{ Ok = $empty; Steps = @($steps); Errors = $errs; After = $after; At = (Get-N5Now) }
}

# ---- the proof gate ---------------------------------------------------------------------------------------------------------------------
$script:N5CodeSetFiles = @('spike-nep5-matrix.ps1', 'spike-nep5-lib.ps1', 'spike-nep5-run-lib.ps1', 'spike-nep5-connect-probe.ps1', 'spike-lib.ps1', 'spike-persist-lib.ps1', 'spike-task-driver.ps1', 'spike-provision.ps1')
$script:N5RequiredTags = @('remove-full-set', 'remove-half-failed-add', 'remove-when-absent', 'remove-reports-delete-error', 'remove-continues-after-error', 'absent-detected', 'unknown-detected',
                           'sweep-finds-foreign-sublayer', 'add-refused-without-proof', 'forged-proof-refused', 'add-refused-over-stale-objects', 'add-failure-rolls-back', 'harness-add-failure-rolls-back',
                           'operator-sid-refused', 'sublayer-allowlist', 'proof-hash-binding', 'removal-direct-proof', 'harness-hash-binding', 'harness-arming', 'harness-live-proof-binding', 'pre-cleanup', 'account-guard', 'secret-not-recorded', 'child-timeout-kill', 'restore-proof',
                           'session-record', 'precondition-dryrun', 'launcher-real', 'account-env', 'task-never-edited', 'check-session', 'seams', 'taskcheck-stamp')
$script:N5ProofMaxAgeHours = 24
$script:N5MinSelfTestChecks = 120
$script:N5ProofNonce = $null

function New-N5HarnessLiveProof {
    # PURE. The file the harness wants behind `--live` (schema nep5-1763-proof-v1): the running exe's SHA-256, the SHA-256 of halfset.rs the exe embeds, checks_failed 0, and a UTC
    # timestamp with a Z. Written ONLY by -SelfTest -WriteProof after the whole self-test passed. The harness checks its form, not whether a self-test ran: the proof of that is the
    # matrix proof this one is bound into.
    param([Parameter(Mandatory)][string]$ExeSha, [Parameter(Mandatory)][string]$RsSha, [int]$ChecksFailed = 0, [datetime]$Now = (Get-Date))
    return [ordered]@{ schema = 'nep5-1763-proof-v1'; halfset_exe_sha256 = $ExeSha.ToLowerInvariant(); halfset_rs_sha256 = $RsSha.ToLowerInvariant(); checks_failed = [int]$ChecksFailed; written_utc = $Now.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
}

function Test-N5HarnessLiveProof {
    # Problems with the harness proof file (empty = it is the one the harness will accept now): a regular file under 1 MiB, the right schema, the exe and halfset.rs hashes equal to
    # the current ones, checks_failed the integer 0, a Z timestamp not older than 24 hours and not in the future.
    param([Parameter(Mandatory)][string]$Path, [string]$ExeSha, [string]$RsSha, [datetimeoffset]$Now = [datetimeoffset]::Now)
    $p = New-Object System.Collections.ArrayList
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @("no harness proof at $Path") }
    if (([IO.FileInfo]$Path).Length -gt 1048576) { return @('the harness proof is over 1 MiB') }
    $j = $null; try { $j = ConvertFrom-Json ([IO.File]::ReadAllText($Path)) } catch { return @("the harness proof does not parse: $($_.Exception.Message)") }
    if ([string]$j.schema -cne 'nep5-1763-proof-v1') { [void]$p.Add('the harness proof has the wrong schema') }
    if (-not $ExeSha -or [string]$j.halfset_exe_sha256 -ne $ExeSha.ToLowerInvariant()) { [void]$p.Add('the harness proof names a different exe hash') }
    if (-not $RsSha -or [string]$j.halfset_rs_sha256 -ne $RsSha.ToLowerInvariant()) { [void]$p.Add('the harness proof names a different halfset.rs hash') }
    if (-not ($j.checks_failed -is [int] -or $j.checks_failed -is [long]) -or [int]$j.checks_failed -ne 0) { [void]$p.Add('the harness proof does not say checks_failed 0') }
    $w = $null; try { $w = ConvertTo-DateTimeOffset $j.written_utc } catch { [void]$p.Add('the harness proof has no readable written_utc') }
    if ($w) { $age = ($Now - $w).TotalHours; if ($age -gt 24) { [void]$p.Add(("the harness proof is {0:N1} h old (limit 24 h)" -f $age)) }; if ($age -lt -0.083) { [void]$p.Add('the harness proof is dated in the future') } }
    return @($p)
}

function Remove-Nep5StaleHarnessProof {
    # The harness proof arms every mutating harness verb for any elevated caller that names it, so it must not outlive the matrix proof it belongs to. Deleted (behind the plain-path guard)
    # when there is no matrix proof, the matrix proof does not parse, the harness proof is OLDER than the matrix proof (it is always written after it), or its hash is not the one the matrix
    # proof recorded. @{ Removed; Reason }.
    param([Parameter(Mandatory)][string]$HarnessProof, [Parameter(Mandatory)][string]$MatrixProof)
    if (-not (Test-Path -LiteralPath $HarnessProof -PathType Leaf)) { return [ordered]@{ Removed = $false; Reason = 'no harness proof file' } }
    $why = $null
    if (-not (Test-Path -LiteralPath $MatrixProof -PathType Leaf)) { $why = 'orphaned: there is no matrix proof' }
    else {
        $mp = $null; try { $mp = ConvertFrom-Json ([IO.File]::ReadAllText($MatrixProof)) } catch { $why = 'orphaned: the matrix proof does not parse' }
        if (-not $why) {
            if ((Get-Item -LiteralPath $HarnessProof).LastWriteTimeUtc -lt (Get-Item -LiteralPath $MatrixProof).LastWriteTimeUtc) { $why = 'older than the matrix proof' }
            elseif (-not $mp.harness -or [string]$mp.harness.live_proof_sha256 -ne (Get-N5RawSha256 -Path $HarnessProof)) { $why = 'not the file the matrix proof recorded' }
        }
    }
    if (-not $why) { return [ordered]@{ Removed = $false; Reason = 'current' } }
    try { Assert-PlainOutputPath -Path $HarnessProof; [IO.File]::Delete($HarnessProof) } catch { return [ordered]@{ Removed = $false; Reason = "stale ($why) and could not be deleted: $($_.Exception.Message)" } }
    return [ordered]@{ Removed = (-not (Test-Path -LiteralPath $HarnessProof)); Reason = $why }
}

function Remove-Nep5StagedHarnessProof {
    # A staged harness proof is a form-valid arming file under another name. Deletes every *.staged file in the folder of the harness proof (behind the plain-path guard). Returns the names removed.
    param([Parameter(Mandatory)][string]$HarnessProof)
    $dir = Split-Path $HarnessProof -Parent; $gone = @()
    if (-not $dir -or -not (Test-Path -LiteralPath $dir -PathType Container)) { return @() }
    foreach ($fi in @(Get-ChildItem -LiteralPath $dir -Filter '*.staged' -File -Force -ErrorAction SilentlyContinue)) { try { Assert-PlainOutputPath -Path $fi.FullName; [IO.File]::Delete($fi.FullName); $gone += $fi.Name } catch {} }
    return @($gone)
}

function Get-N5CodeSetHashes {
    # name -> hash for every file of the new code set in $Folder; a missing file is reported by name, never skipped. A library this process loaded through
    # Get-VerifiedLibBlock is represented by the hash of the bytes it ran, not by a fresh read of the path.
    param([Parameter(Mandatory)][string]$Folder)
    $h = [ordered]@{}; $missing = @()
    foreach ($n in $script:N5CodeSetFiles) {
        $p = Join-Path $Folder $n
        if ($script:LoadedLibHashes -and $script:LoadedLibHashes.ContainsKey($n) -and $script:LoadedLibFolder -and ($script:LoadedLibFolder.TrimEnd('\', '/') -eq $Folder.TrimEnd('\', '/'))) { $h[$n] = $script:LoadedLibHashes[$n] }
        elseif (Test-Path -LiteralPath $p) { $h[$n] = Get-NormalizedSha256 -Path $p } else { $missing += $n }
    }
    return [pscustomobject]@{ Hashes = $h; Missing = $missing }
}

function Get-N5HarnessHashes {
    # The three raw hashes the proof binds besides the scripts: the harness exe, halfset.rs and the pinned Cargo.lock. $null per item when unreadable.
    param([string]$Exe, [string]$Source, [string]$CargoLock)
    return [ordered]@{ exe_sha256 = $(if ($Exe) { Get-N5RawSha256 -Path $Exe }); source_sha256 = $(if ($Source) { Get-N5RawSha256 -Path $Source }); cargo_lock_sha256 = $(if ($CargoLock) { Get-N5RawSha256 -Path $CargoLock }) }
}

function New-N5ProofObject {
    # PURE on its arguments. The record -SelfTest -WriteProof saves.
    param($Hashes, $Harness, [string[]]$PassedTags, [string[]]$FailedChecks, [string]$HostInfo, [string]$When, [string]$WrappedHash = '', [int]$ChecksRun = 0, [int]$ChecksPassed = 0, $Siblings = @(), $HarnessChecks = $null)
    $all = @($script:N5RequiredTags | Where-Object { $PassedTags -contains $_ })
    return [ordered]@{
        schema = 1; kind = 'nep5-rollback-selftest-proof'; written = $When; host = $HostInfo; sha256_lf_normalised = $Hashes
        wrapped_script_sha256 = $WrappedHash; harness = $Harness; harness_checks = $HarnessChecks
        selftest = [ordered]@{ checks_run = $ChecksRun; checks_passed = $ChecksPassed }
        sibling_selftests = @($Siblings)
        rollback_tags_passed = @($PassedTags | Select-Object -Unique); rollback_tags_required = @($script:N5RequiredTags)
        failed_checks = @($FailedChecks); passed = (@($FailedChecks).Count -eq 0 -and $all.Count -eq $script:N5RequiredTags.Count)
    }
}

function Get-N5ChecksCeiling {
    # The most checks a real -SelfTest can run: the number of `Chk` command calls in the two scripts that make them, counted by the PowerShell parser (a call after `try {` or
    # `else {` on the same line counts like any other), plus 30 for the checks that sit in loops and for the -WriteProof ones. 0 when the scripts are absent.
    param([Parameter(Mandatory)][string]$Folder)
    $n = 0
    foreach ($f in @('spike-nep5-matrix.ps1', 'spike-nep5-run-lib.ps1')) {
        $p = Join-Path $Folder $f
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $tokens = $null; $errs = $null; $ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $p).Path, [ref]$tokens, [ref]$errs)
        $n += @($ast.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -eq 'Chk' }, $true)).Count
    }
    if ($n -eq 0) { return 0 }
    return ($n + 30)
}

function Test-N5Proof {
    # Returns the token the add paths demand: @{ Kind = 'Nep5Proof'; Ok; Problems[]; Nonce; Written }. Ok only when the file exists, parses, says passed, lists every
    # required tag, is younger than the age limit, carries a real self-test record, and EVERY hash it holds equals the hash now: each script of the code set, the wrapped
    # #1671 script, the harness exe, halfset.rs and the pinned Cargo.lock (which must also equal the recorded pin). Ok tokens carry a per-process nonce.
    param([Parameter(Mandatory)][string]$ProofPath, [Parameter(Mandatory)][string]$Folder, [string]$WrappedSha256, [string]$HarnessExe, [string]$HarnessSource, [string]$CargoLock, [string]$HarnessLiveProof, [datetimeoffset]$Now = [datetimeoffset]::Now, [int]$MaxAgeHours = $script:N5ProofMaxAgeHours)
    $problems = New-Object System.Collections.ArrayList
    $tok = [pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $false; Problems = @(); ProofPath = $ProofPath; Written = $null; Nonce = $null; ProbeSha = $null; HarnessSha = $null; ProvisionSha = $null; ProvisionLibSha = $null }
    if (-not (Test-Path -LiteralPath $ProofPath)) { [void]$problems.Add("no rollback self-test proof at ${ProofPath}: run spike-nep5-matrix.ps1 -SelfTest -WriteProof first"); $tok.Problems = @($problems); return $tok }
    $p = $null
    try { $p = ConvertFrom-Json ([IO.File]::ReadAllText($ProofPath)) } catch { [void]$problems.Add("proof file does not parse: $($_.Exception.Message)"); $tok.Problems = @($problems); return $tok }
    if ($p.kind -ne 'nep5-rollback-selftest-proof') { [void]$problems.Add('proof file is not a nep5-rollback-selftest-proof') }
    if ($p.schema -ne 1) { [void]$problems.Add("proof schema $($p.schema) is not 1: re-run the self-test with these scripts") }
    if (-not $p.passed) { [void]$problems.Add('the recorded self-test did not pass') }
    if (@($p.failed_checks).Count) { [void]$problems.Add("the proof records failed checks: $((@($p.failed_checks) | Select-Object -First 3) -join '; ')") }
    if (-not $p.selftest -or [int]$p.selftest.checks_run -lt $script:N5MinSelfTestChecks -or [int]$p.selftest.checks_passed -ne [int]$p.selftest.checks_run) { [void]$problems.Add("the proof does not record a self-test run (at least $($script:N5MinSelfTestChecks) checks, all passed)") }
    $sib = @($p.sibling_selftests)
    if ($sib.Count -lt 1 -or @($sib | Where-Object { -not $_.passed -or [int]$_.checks -lt 5 }).Count) { [void]$problems.Add('the proof does not record every sibling self-test as passed') }
    if (-not $p.harness_checks -or -not $p.harness_checks.refusals_exit_zero -or -not $p.harness_checks.engine_open_trace_empty) { [void]$problems.Add('the proof does not record the harness refusal self-test as passed with an empty engine-open trace') }
    if (-not $WrappedSha256) { [void]$problems.Add('no hash of the wrapped #1671 script was supplied') }
    elseif (-not $p.wrapped_script_sha256) { [void]$problems.Add('the proof has no hash of the wrapped #1671 script') }
    elseif ([string]$p.wrapped_script_sha256 -ne $WrappedSha256.ToUpperInvariant()) { [void]$problems.Add('the wrapped #1671 script changed since the self-test') }
    $nowH = Get-N5HarnessHashes -Exe $HarnessExe -Source $HarnessSource -CargoLock $CargoLock
    foreach ($pair in @(@('exe_sha256', 'the harness exe'), @('source_sha256', 'halfset.rs'), @('cargo_lock_sha256', 'the pinned Cargo.lock'))) {
        $was = if ($p.harness) { [string]$p.harness.($pair[0]) } else { '' }; $cur = $nowH[$pair[0]]
        if (-not $was) { [void]$problems.Add("the proof has no hash of $($pair[1])") }
        elseif (-not $cur) { [void]$problems.Add("$($pair[1]) cannot be read now") }
        elseif ($was -ne $cur) { [void]$problems.Add("$($pair[1]) changed since the self-test (proof $($was.Substring(0, 12))..., now $($cur.Substring(0, 12))...)") }
    }
    # the harness's own proof file: the form the harness will accept now, and the very file this proof was written with
    if (-not $HarnessLiveProof) { [void]$problems.Add('no harness proof path was supplied') }
    else {
        foreach ($m in @(Test-N5HarnessLiveProof -Path $HarnessLiveProof -ExeSha $nowH.exe_sha256 -RsSha $nowH.source_sha256 -Now $Now)) { [void]$problems.Add($m) }
        $lpNow = Get-N5RawSha256 -Path $HarnessLiveProof; $lpWas = if ($p.harness) { [string]$p.harness.live_proof_sha256 } else { '' }
        if (-not $lpWas) { [void]$problems.Add('the proof has no hash of the harness proof file') } elseif (-not $lpNow -or $lpNow -ne $lpWas) { [void]$problems.Add('the harness proof file is not the one this proof was written with') }
    }
    if ($nowH.cargo_lock_sha256 -and $nowH.cargo_lock_sha256 -ne $script:N5PinnedCargoLockSha256) { [void]$problems.Add('the Cargo.lock beside the harness is not the pinned one') }
    $ceil = Get-N5ChecksCeiling -Folder $Folder
    if ($ceil -le 0) { [void]$problems.Add('cannot judge whether the recorded number of checks is plausible: the matrix scripts are not in the folder') }
    elseif ($p.selftest -and [int]$p.selftest.checks_run -gt $ceil) { [void]$problems.Add("the proof claims $([int]$p.selftest.checks_run) checks run but the self-test has at most $ceil check sites: not a real run") }
    $tags = @($p.rollback_tags_passed)
    foreach ($t in $script:N5RequiredTags) { if ($tags -notcontains $t) { [void]$problems.Add("rollback check '$t' is not in the proof") } }
    try {
        $w = ConvertTo-DateTimeOffset $p.written; $tok.Written = $w
        $age = ($Now - $w).TotalHours
        if ($age -gt $MaxAgeHours) { [void]$problems.Add(("proof is {0:N1} h old (limit {1} h): re-run the self-test" -f $age, $MaxAgeHours)) }
        if ($age -lt -0.1) { [void]$problems.Add('proof is dated in the future') }
    } catch { [void]$problems.Add("proof timestamp unreadable: $($_.Exception.Message)") }
    $cur = Get-N5CodeSetHashes -Folder $Folder
    foreach ($m in $cur.Missing) { [void]$problems.Add("code-set file missing from ${Folder}: $m") }
    $rec = $p.sha256_lf_normalised
    foreach ($n in $cur.Hashes.Keys) {
        $was = if ($rec) { [string]$rec.$n } else { '' }
        if (-not $was) { [void]$problems.Add("proof has no hash for $n") }
        elseif ($was -ne $cur.Hashes[$n]) { [void]$problems.Add("$n changed since the self-test (proof $($was.Substring(0, 12))..., now $($cur.Hashes[$n].Substring(0, 12))...): re-run the self-test") }
    }
    $tok.Problems = @($problems); $tok.Ok = ($problems.Count -eq 0)
    if ($tok.Ok) { $script:N5ProofNonce = [guid]::NewGuid().ToString('N'); $tok.Nonce = $script:N5ProofNonce; $tok.ProbeSha = $cur.Hashes['spike-nep5-connect-probe.ps1']; $tok.HarnessSha = $nowH.exe_sha256; $tok.ProvisionSha = $cur.Hashes['spike-provision.ps1']; $tok.ProvisionLibSha = $cur.Hashes['spike-lib.ps1'] }   # the hashes this check VERIFIED against the proof: what the run binds to
    return $tok
}

function Test-N5ProofToken {
    # The check every add path runs on the token it was handed: the right kind, Ok, and the nonce only Test-N5Proof of THIS process hands out.
    param($Proof)
    return [bool]($null -ne $Proof -and $Proof.PSObject.Properties['Kind'] -and $Proof.Kind -eq 'Nep5Proof' -and $Proof.PSObject.Properties['Ok'] -and $Proof.Ok -eq $true -and
                  $Proof.PSObject.Properties['Nonce'] -and $Proof.Nonce -and $script:N5ProofNonce -and ([string]$Proof.Nonce -eq $script:N5ProofNonce))
}

# ---- the add paths (the ONLY ones): proof, SID, sublayer, empty-sweep gates; rollback by key on any failure -------------------------------
function Add-Nep5SrtWinSet {
    # srt-win's own full set through the harness `install`, for one of the two test SIDs, in S1 (or another allowed sublayer). Refuses without a valid token, with a
    # SID problem, with a sublayer that is not allowed, or over any existing object; rolls back by key if the install fails or reads back wrong.
    # $SidProblems is the SID-safety verdict (computed by the caller from the operator's token); $ProofValidator and $SublayerGate are switchable for the OFF tests.
    param([Parameter(Mandatory)][scriptblock]$Runner, $Backend, [Parameter(Mandatory)][string]$SubLayer, [Parameter(Mandatory)][string]$Sid, [string[]]$SidProblems = @('no SID verdict supplied'), $Proof,
          [scriptblock]$ProofValidator = { param($p) Test-N5ProofToken $p }, [scriptblock]$SublayerGate = { param($s) [bool](Get-N5SubLayerId $s) })
    $refuse = { param($why) return [ordered]@{ Ok = $false; Refused = $true; Added = $false; Reason = "refused: $why (nothing added)" } }
    if (-not (& $ProofValidator $Proof)) { return (& $refuse 'no valid rollback self-test proof') }
    if (-not (& $SublayerGate $SubLayer)) { return (& $refuse "sublayer $SubLayer is not S1, S2 or S3") }
    if (@($SidProblems).Count) { return (& $refuse "SID not safe: $(@($SidProblems) -join '; ')") }
    $pre = Get-Nep5Residue -Runner $Runner -Backend $Backend
    if (-not $pre.Readable) { return (& $refuse "the engine could not be read before the add: $(@($pre.Problems) -join '; ')") }
    if ($pre.Total -gt 0 -or $pre.Foreign.Count -gt 0 -or $pre.ProviderPresent -or @($pre.SubLayers.Values | Where-Object { $_.present }).Count) { return (& $refuse 'stale objects are present; run -Remove first') }
    $inst = Invoke-Halfset -Runner $Runner -Argv @('install', '--sublayer', $SubLayer, '--sid', $Sid)
    $fail = $null
    if ($inst.ExitCode -ne 0) { $fail = "harness install exited $($inst.ExitCode) ($($inst.Outcome))" }
    else {
        $en = Invoke-Halfset -Runner $Runner -Argv @('enum', '--sublayer', $SubLayer)
        $pe = $(if ($en.ExitCode -eq 0) { ConvertFrom-HarnessFilters -Json $en.Json } else { [ordered]@{ Ok = $false; Rows = @(); Problem = "exit $($en.ExitCode)" } })
        if (-not $pe.Ok -or @($pe.Rows).Count -lt 1) { $fail = "the install read back as empty or unreadable ($($pe.Problem))" }
    }
    if ($fail) {
        $rb = Remove-Nep5All -Runner $Runner -Backend $Backend
        return [ordered]@{ Ok = $false; Refused = $false; Added = $false; Reason = "install failed: $fail; rolled back by key, direct re-read clean: $($rb.Ok)"; Install = $inst; Rollback = $rb }
    }
    return [ordered]@{ Ok = $true; Refused = $false; Added = $true; Reason = 'installed'; Install = $inst; At = (Get-N5Now) }
}

function Add-Nep5OurPlan {
    # Our own adder: the plan's set transaction, then each attempt one by one (the engine's answer is the result). Gates as above; the pre-state of EVERY object the plan
    # names must read absent; any failure, or a read-back that is not whole, rolls back by key. An attempt that names the missing sublayer and is ACCEPTED is deleted at once
    # and is a STOP (Stop = $true): it created a filter outside S1/S2/S3.
    param([Parameter(Mandatory)][scriptblock]$Runner, [Parameter(Mandatory)]$Backend, [Parameter(Mandatory)]$Plan, [string[]]$SidProblems = @('no SID verdict supplied'), $Proof,
          [scriptblock]$ProofValidator = { param($p) Test-N5ProofToken $p }, [scriptblock]$PlanGate = { param($pl) @(Get-Nep5PlanProblems -Plan $pl) })
    $refuse = { param($why) return [ordered]@{ Ok = $false; Refused = $true; Added = $false; Stop = $false; Reason = "refused: $why (nothing added)"; Attempts = @() } }
    if (-not (& $ProofValidator $Proof)) { return (& $refuse 'no valid rollback self-test proof') }
    $pp = @(& $PlanGate $Plan)
    if ($pp.Count) { return (& $refuse "plan refused: $($pp -join '; ')") }
    if (@($SidProblems).Count) { return (& $refuse "SID not safe: $(@($SidProblems) -join '; ')") }
    $names = @(); if ($Plan.Provider) { $names += , @('provider', $script:N5ProviderKey) }; if ($Plan.SubLayer) { $names += , @('sublayer', $Plan.SubLayer) }
    foreach ($f in @($Plan.Filters) + @($Plan.Attempts)) { if ($f) { $names += , @('filter', $f.Key) } }
    try {
        foreach ($n in $names) { if ([long]$Backend.Flags($n[0], $n[1]) -ge 0) { return (& $refuse "$($n[0]) $($n[1]) already exists (stale object); run -Remove first") } }
    } catch { return (& $refuse "the engine could not be read before the add: $($_.Exception.Message)") }
    $attempts = @(); $stop = $false; $fail = $null
    if ($Plan.Provider -or $Plan.SubLayer -or @($Plan.Filters).Count) {
        try { [void]@($Backend.AddSet($Plan)) } catch { $fail = "add failed: $($_.Exception.Message)" }
    }
    if (-not $fail) {
        foreach ($f in @($Plan.Attempts)) {
            $st = 'error: not attempted'
            try { $st = [string]$Backend.AddOne($f) } catch { $st = "error: $($_.Exception.Message)" }
            $row = [ordered]@{ id = $f.Id; key = $f.Key; status = $st; deleted_at_once = $false }
            if ($st -eq 'added' -and (ConvertTo-N5Guid $f.SubLayer) -eq $script:N5MissingSubLayer) {
                $row.deleted_at_once = $true; try { $row.delete_status = [string]$Backend.Delete('filter', $f.Key) } catch { $row.delete_status = "error: $($_.Exception.Message)" }
                $stop = $true
            }
            $attempts += , $row
        }
    }
    if (-not $fail -and -not $stop) {
        try {
            if ($Plan.Provider -and [long]$Backend.Flags('provider', $script:N5ProviderKey) -lt 0) { $fail = 'read-back: the provider is missing' }
            if (-not $fail -and $Plan.SubLayer -and [long]$Backend.Flags('sublayer', $Plan.SubLayer) -lt 0) { $fail = 'read-back: the sublayer is missing' }
            if (-not $fail) { foreach ($f in @($Plan.Filters)) { $fl = [long]$Backend.Flags('filter', $f.Key); if ($fl -lt 0) { $fail = "read-back: filter $($f.Id) is missing"; break }; if (($fl -band 1) -eq 0) { $fail = "read-back: filter $($f.Id) is not persistent"; break } } }
        } catch { $fail = "read-back failed: $($_.Exception.Message)" }
    }
    if ($fail -or $stop) {
        $rb = Remove-Nep5All -Runner $Runner -Backend $Backend
        $why = if ($stop) { 'an attempt naming the missing sublayer was ACCEPTED (deleted at once): STOP' } else { "$fail; rolled back by key" }
        return [ordered]@{ Ok = $false; Refused = $false; Added = $false; Stop = $stop; Reason = $why; Attempts = $attempts; Rollback = $rb }
    }
    return [ordered]@{ Ok = $true; Refused = $false; Added = $true; Stop = $false; Reason = 'added'; Attempts = $attempts; At = (Get-N5Now) }
}
