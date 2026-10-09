#requires -Version 5.1
<#
.SYNOPSIS
  #1671 spike: does a RAW Windows Filtering Platform (WFP) BLOCK filter keyed to the blarai-coder
  account enforce on this machine while Bitdefender owns packet filtering?

.DESCRIPTION
  Modes (exactly one):
    -SelfTest   pure helpers only (SD builder, arg validation, exit-code decision, struct sizes). No system change.
    -DryRun     resolve the coder SID, build every struct + the security descriptor in memory, print them,
                compile the C#, open the BFE engine READ-ONLY (adds nothing) and look for our sublayer.
    -Live       the real test. Run ONLY with the Lead Architect at the machine, elevated.

  SAFETY MODEL
    * Every object is added through a DYNAMIC WFP session (FWPM_SESSION_FLAG_DYNAMIC): the kernel removes
      provider, sublayer and all filters when the engine handle closes OR this process dies. Nothing is
      persistent. This is the primary rollback.
    * Dead-man: a CLR timer thread closes the engine handle after HoldSeconds+30 s even if PowerShell hangs.
    * Every filter carries the coder-user condition (ALE_USER_ID); no filter is ever added without it.
    * Watchdog: operator-process connect to 1.1.1.1:443 every 2 s while filters are live; two consecutive
      failures remove everything and exit 3.

  EXIT CODES
    0 coder blocked, loopback ok, operator unaffected, removal verified
    1 coder NOT blocked (answer: raw WFP does not enforce under Bitdefender)
    2 precondition / argument failure (nothing was added)
    3 operator traffic affected (aborted, everything removed)
    4 inconclusive (coder probe produced no usable result, operator isolated failure, loopback not ok, error)
    5 no baseline (operator offline, or the coder was ALREADY blocked before our filters)
    7 removal NOT verified (highest severity; check by hand: this process exiting also removes everything)
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Live,
    [switch]$SelfTest,
    [int]$HoldSeconds = 60,
    [string]$CoderUser = 'blarai-coder',
    [string]$AgenticScripts = 'C:\Users\_OPERATOR_\agentic-setup\scripts',
    [string]$OutDir = 'C:\Users\_OPERATOR_\blarai-research-data\wfp-spike',
    [string]$LoopbackUrl = 'http://127.0.0.1:8000/v3/models',
    [string]$TaskPath = '\BlarAI\',
    [string]$TaskName = 'BlarAI-Coder-Leg',
    [string]$FirewallRuleName = 'blarai-coder-deny-outbound'
)
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------------------------
# Embedded C# (C# 5 compatible: Windows PowerShell 5.1 compiles with csc 4.x).
# GUIDs/constants cite: Windows SDK 10.0.26100.0 um/fwpmu.h, shared/fwptypes.h, shared/fwpmtypes.h.
# ---------------------------------------------------------------------------------------------
$csharp = @'
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

namespace BlarAI.Wfp
{
    [StructLayout(LayoutKind.Sequential)]
    public struct FWP_BYTE_BLOB { public uint size; public IntPtr data; }

    // FWP_VALUE0 and FWP_CONDITION_VALUE0: DWORD type + a union whose widest arm is pointer-sized
    // (fwptypes.h: every wide arm is a pointer; uint8/16/32 live inline in the low bytes).
    [StructLayout(LayoutKind.Sequential)]
    public struct FWP_VALUE0 { public uint type; public IntPtr value; }

    [StructLayout(LayoutKind.Sequential)]
    public struct FWPM_DISPLAY_DATA0 { public IntPtr name; public IntPtr description; }

    [StructLayout(LayoutKind.Sequential)]
    public struct FWPM_SESSION0
    {
        public Guid sessionKey; public FWPM_DISPLAY_DATA0 displayData; public uint flags;
        public uint txnWaitTimeoutInMSec; public uint processId; public IntPtr sid; public IntPtr username; public int kernelMode;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct FWPM_PROVIDER0
    {
        public Guid providerKey; public FWPM_DISPLAY_DATA0 displayData; public uint flags;
        public FWP_BYTE_BLOB providerData; public IntPtr serviceName;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct FWPM_SUBLAYER0
    {
        public Guid subLayerKey; public FWPM_DISPLAY_DATA0 displayData; public uint flags;
        public IntPtr providerKey; public FWP_BYTE_BLOB providerData; public ushort weight;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct FWPM_ACTION0 { public uint type; public Guid filterType; }

    [StructLayout(LayoutKind.Sequential)]
    public struct FWPM_FILTER_CONDITION0 { public Guid fieldKey; public uint matchType; public FWP_VALUE0 conditionValue; }

    // The anonymous union { UINT64 rawContext; GUID providerContextKey; }: 16 bytes, 8-aligned.
    [StructLayout(LayoutKind.Sequential)]
    public struct FILTER_CONTEXT_UNION { public ulong a; public ulong b; }

    [StructLayout(LayoutKind.Sequential)]
    public struct FWPM_FILTER0
    {
        public Guid filterKey; public FWPM_DISPLAY_DATA0 displayData; public uint flags;
        public IntPtr providerKey; public FWP_BYTE_BLOB providerData; public Guid layerKey; public Guid subLayerKey;
        public FWP_VALUE0 weight; public uint numFilterConditions; public IntPtr filterCondition;
        public FWPM_ACTION0 action; public FILTER_CONTEXT_UNION context; public IntPtr reserved;
        public ulong filterId; public FWP_VALUE0 effectiveWeight;
    }

    public static class Native
    {
        [DllImport("fwpuclnt.dll", CharSet = CharSet.Unicode)]
        public static extern uint FwpmEngineOpen0(string serverName, uint authnService, IntPtr authIdentity, ref FWPM_SESSION0 session, out IntPtr engineHandle);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmEngineClose0(IntPtr engineHandle);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmTransactionBegin0(IntPtr engineHandle, uint flags);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmTransactionCommit0(IntPtr engineHandle);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmTransactionAbort0(IntPtr engineHandle);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmProviderAdd0(IntPtr engineHandle, ref FWPM_PROVIDER0 provider, IntPtr sd);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmSubLayerAdd0(IntPtr engineHandle, ref FWPM_SUBLAYER0 subLayer, IntPtr sd);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmFilterAdd0(IntPtr engineHandle, ref FWPM_FILTER0 filter, IntPtr sd, out ulong id);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmProviderGetByKey0(IntPtr engineHandle, ref Guid key, out IntPtr provider);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmSubLayerGetByKey0(IntPtr engineHandle, ref Guid key, out IntPtr subLayer);
        [DllImport("fwpuclnt.dll")] public static extern uint FwpmFilterGetByKey0(IntPtr engineHandle, ref Guid key, out IntPtr filter);
        [DllImport("fwpuclnt.dll")] public static extern void FwpmFreeMemory0(ref IntPtr p);
    }

    public class FilterSpec
    {
        public Guid Key; public string Name; public string LayerName; public Guid Layer;
        public uint Action; public ulong Weight; public bool Loopback;   // every filter ALSO carries the user condition
    }

    public sealed class Plan
    {
        // Provenance: each GUID below was read from the installed Windows SDK header named, 2026-10-04.
        // um/fwpmu.h: FWPM_LAYER_ALE_AUTH_CONNECT_V4, FWPM_LAYER_ALE_AUTH_CONNECT_V6, FWPM_CONDITION_ALE_USER_ID, FWPM_CONDITION_FLAGS.
        public static readonly Guid LayerConnectV4 = new Guid("c38d57d1-05a7-4c33-904f-7fbceee60e82");
        public static readonly Guid LayerConnectV6 = new Guid("4a72393b-319f-44bc-84c3-ba54dcb3b6b4");
        public static readonly Guid CondAleUserId  = new Guid("af043a0a-b34d-4f86-979c-c90371af6e66");
        public static readonly Guid CondFlags      = new Guid("632ce23b-5167-435c-86d7-e903684aa80c");
        // Our own keys (generated for this spike; not Microsoft values).
        public static readonly Guid ProviderKey = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e1f01");
        public static readonly Guid SubLayerKey = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e1f02");
        // fwptypes.h constants.
        public const uint FWP_UINT32 = 3, FWP_UINT64 = 4, FWP_SECURITY_DESCRIPTOR_TYPE = 14;
        public const uint FWP_MATCH_EQUAL = 0, FWP_MATCH_FLAGS_ALL_SET = 6;
        public const uint FWP_ACTION_BLOCK = 0x1001, FWP_ACTION_PERMIT = 0x1002;   // 0x1000 TERMINATING | 1 / 2
        public const uint FWP_CONDITION_FLAG_IS_LOOPBACK = 1, FWP_ACTRL_MATCH_FILTER = 1;
        public const uint FWPM_SESSION_FLAG_DYNAMIC = 1;                          // fwpmtypes.h
        public const ushort SubLayerWeight = 0xFFFF;
        public const ulong PermitWeight = 0x2000, BlockWeight = 0x1000;

        public string CoderSid; public byte[] Sd; public string Sddl; public List<FilterSpec> Filters = new List<FilterSpec>();

        public static bool IsAcceptableCoderSid(string sid)
        {
            // Account-domain SID only: S-1-5-21-a-b-c-RID. Rejects Everyone, Users, Authenticated Users, SYSTEM, groups like Administrators.
            return sid != null && Regex.IsMatch(sid, @"^S-1-5-21-\d+-\d+-\d+-\d{3,}$");
        }

        public static byte[] BuildSd(string sid)
        {
            SecurityIdentifier si = new SecurityIdentifier(sid);
            RawAcl acl = new RawAcl(2, 1);
            acl.InsertAce(0, new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, (int)FWP_ACTRL_MATCH_FILTER, si, false, null));
            RawSecurityDescriptor sd = new RawSecurityDescriptor(ControlFlags.DiscretionaryAclPresent, null, null, null, acl);
            byte[] b = new byte[sd.BinaryLength];
            sd.GetBinaryForm(b, 0);
            return b;
        }

        public static Plan Build(string sid)
        {
            if (!IsAcceptableCoderSid(sid)) throw new ArgumentException("refusing SID (not an account-domain user SID): " + sid);
            Plan p = new Plan(); p.CoderSid = sid; p.Sd = BuildSd(sid);
            p.Sddl = new RawSecurityDescriptor(p.Sd, 0).GetSddlForm(AccessControlSections.Access);
            p.Filters.Add(Mk("f1100001-0000-4d8e-9a31-2b6d4c8e1f11", "permit-loopback-coder-v4", "ALE_AUTH_CONNECT_V4", LayerConnectV4, FWP_ACTION_PERMIT, PermitWeight, true));
            p.Filters.Add(Mk("f1100002-0000-4d8e-9a31-2b6d4c8e1f12", "permit-loopback-coder-v6", "ALE_AUTH_CONNECT_V6", LayerConnectV6, FWP_ACTION_PERMIT, PermitWeight, true));
            p.Filters.Add(Mk("f1100003-0000-4d8e-9a31-2b6d4c8e1f21", "block-coder-v4", "ALE_AUTH_CONNECT_V4", LayerConnectV4, FWP_ACTION_BLOCK, BlockWeight, false));
            p.Filters.Add(Mk("f1100004-0000-4d8e-9a31-2b6d4c8e1f22", "block-coder-v6", "ALE_AUTH_CONNECT_V6", LayerConnectV6, FWP_ACTION_BLOCK, BlockWeight, false));
            return p;
        }

        static FilterSpec Mk(string key, string name, string layerName, Guid layer, uint action, ulong weight, bool loop)
        {
            FilterSpec f = new FilterSpec(); f.Key = new Guid(key); f.Name = "BlarAI #1671 spike: " + name; f.LayerName = layerName;
            f.Layer = layer; f.Action = action; f.Weight = weight; f.Loopback = loop; return f;
        }

        public string Describe()
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("coder SID      : " + CoderSid);
            sb.AppendLine("SD (SDDL)      : " + Sddl);
            sb.AppendLine("SD bytes       : " + Sd.Length + " : " + BitConverter.ToString(Sd));
            sb.AppendLine("provider       : " + ProviderKey + "  (non-persistent, dynamic session)");
            sb.AppendLine("sublayer       : " + SubLayerKey + "  weight=0x" + SubLayerWeight.ToString("X"));
            foreach (FilterSpec f in Filters)
            {
                sb.AppendLine("filter " + f.Key + "  " + f.Name);
                sb.AppendLine("   layer " + f.LayerName + " " + f.Layer + "  action=" + (f.Action == FWP_ACTION_BLOCK ? "BLOCK(0x1001)" : "PERMIT(0x1002)") + "  weight=FWP_UINT64 0x" + f.Weight.ToString("X"));
                if (f.Loopback) sb.AppendLine("   cond  FWPM_CONDITION_FLAGS " + CondFlags + "  FWP_MATCH_FLAGS_ALL_SET  FWP_UINT32 0x1 (FWP_CONDITION_FLAG_IS_LOOPBACK)");
                sb.AppendLine("   cond  FWPM_CONDITION_ALE_USER_ID " + CondAleUserId + "  FWP_MATCH_EQUAL  FWP_SECURITY_DESCRIPTOR_TYPE(14) -> SD above");
            }
            return sb.ToString();
        }
    }

    // All unmanaged memory for one Plan. BFE copies everything during Add, so Free() after the transaction is safe.
    public sealed class Marshalled
    {
        public List<IntPtr> Allocs = new List<IntPtr>();
        public FWPM_PROVIDER0 Provider; public FWPM_SUBLAYER0 SubLayer;
        public List<FWPM_FILTER0> Filters = new List<FWPM_FILTER0>();
        public List<byte[]> FilterImages = new List<byte[]>(); public List<byte[]> CondImages = new List<byte[]>();
        public byte[] ProviderImage, SubLayerImage;

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

        public static Marshalled Build(Plan plan)
        {
            Marshalled m = new Marshalled();
            IntPtr provKeyPtr = m.GuidPtr(Plan.ProviderKey);
            m.Provider = new FWPM_PROVIDER0(); m.Provider.providerKey = Plan.ProviderKey;
            m.Provider.displayData = m.DD("BlarAI #1671 spike provider", "Temporary dynamic provider; removed when the engine handle closes.");
            m.ProviderImage = Image(m.Provider);
            m.SubLayer = new FWPM_SUBLAYER0(); m.SubLayer.subLayerKey = Plan.SubLayerKey; m.SubLayer.providerKey = provKeyPtr;
            m.SubLayer.displayData = m.DD("BlarAI #1671 spike sublayer", "Temporary dynamic sublayer; removed when the engine handle closes.");
            m.SubLayer.weight = Plan.SubLayerWeight; m.SubLayerImage = Image(m.SubLayer);

            IntPtr sdBlob = m.Blob(plan.Sd);
            int condSize = Marshal.SizeOf(typeof(FWPM_FILTER_CONDITION0));
            foreach (FilterSpec f in plan.Filters)
            {
                List<FWPM_FILTER_CONDITION0> conds = new List<FWPM_FILTER_CONDITION0>();
                if (f.Loopback)
                {
                    FWPM_FILTER_CONDITION0 c = new FWPM_FILTER_CONDITION0(); c.fieldKey = Plan.CondFlags; c.matchType = Plan.FWP_MATCH_FLAGS_ALL_SET;
                    c.conditionValue.type = Plan.FWP_UINT32; c.conditionValue.value = new IntPtr((int)Plan.FWP_CONDITION_FLAG_IS_LOOPBACK); conds.Add(c);
                }
                FWPM_FILTER_CONDITION0 u = new FWPM_FILTER_CONDITION0(); u.fieldKey = Plan.CondAleUserId; u.matchType = Plan.FWP_MATCH_EQUAL;
                u.conditionValue.type = Plan.FWP_SECURITY_DESCRIPTOR_TYPE; u.conditionValue.value = sdBlob; conds.Add(u);

                IntPtr arr = m.A(condSize * conds.Count);
                for (int i = 0; i < conds.Count; i++)
                {
                    Marshal.StructureToPtr(conds[i], new IntPtr(arr.ToInt64() + (long)i * condSize), false);
                    m.CondImages.Add(Image(conds[i]));
                }
                FWPM_FILTER0 fl = new FWPM_FILTER0(); fl.filterKey = f.Key; fl.displayData = m.DD(f.Name, "Temporary dynamic filter, keyed to the coder user.");
                fl.flags = 0; fl.providerKey = provKeyPtr; fl.layerKey = f.Layer; fl.subLayerKey = Plan.SubLayerKey;
                fl.weight.type = Plan.FWP_UINT64; fl.weight.value = m.U64(f.Weight);
                fl.numFilterConditions = (uint)conds.Count; fl.filterCondition = arr; fl.action.type = f.Action;
                m.Filters.Add(fl); m.FilterImages.Add(Image(fl));
            }
            return m;
        }

        public void Free() { foreach (IntPtr p in Allocs) Marshal.FreeHGlobal(p); Allocs.Clear(); }
    }

    public sealed class Engine
    {
        IntPtr handle; readonly object gate = new object(); Timer deadMan; public uint LastCloseStatus;
        public bool IsOpen { get { lock (gate) { return handle != IntPtr.Zero; } } }

        public static Engine Open(bool dynamicSession, string name)
        {
            FWPM_SESSION0 s = new FWPM_SESSION0();
            IntPtr nm = Marshal.StringToHGlobalUni(name);
            try
            {
                s.displayData.name = nm; s.flags = dynamicSession ? Plan.FWPM_SESSION_FLAG_DYNAMIC : 0; s.txnWaitTimeoutInMSec = 10000;
                IntPtr h;
                uint rc = Native.FwpmEngineOpen0(null, 0xFFFFFFFF, IntPtr.Zero, ref s, out h);   // RPC_C_AUTHN_DEFAULT (rpcdce.h)
                if (rc != 0) throw new InvalidOperationException("FwpmEngineOpen0 failed 0x" + rc.ToString("X8"));
                Engine e = new Engine(); e.handle = h; return e;
            }
            finally { Marshal.FreeHGlobal(nm); }
        }

        // Independent of the PowerShell thread: closes the handle (=> dynamic objects vanish) after N seconds.
        public void ArmDeadMan(int seconds) { deadMan = new Timer(delegate(object o) { Close(); }, null, seconds * 1000, Timeout.Infinite); }

        public void Close()
        {
            lock (gate)
            {
                if (handle == IntPtr.Zero) return;
                LastCloseStatus = Native.FwpmEngineClose0(handle); handle = IntPtr.Zero;
            }
        }

        static void Check(string what, uint rc) { if (rc != 0) throw new InvalidOperationException(what + " failed 0x" + rc.ToString("X8")); }

        public ulong[] AddAll(Plan plan)
        {
            Marshalled m = Marshalled.Build(plan); bool inTxn = false; List<ulong> ids = new List<ulong>();
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

        // Returns true=exists, false=not found (FWP_E_xxx_NOT_FOUND per winerror.h), throws on anything else.
        static bool Exists(string what, uint rc, IntPtr obj, uint notFound)
        {
            if (rc == 0) { Native.FwpmFreeMemory0(ref obj); return true; }
            if (rc == notFound) return false;
            throw new InvalidOperationException(what + " lookup failed 0x" + rc.ToString("X8"));
        }
        public bool SubLayerExists() { Guid k = Plan.SubLayerKey; IntPtr o; lock (gate) { return Exists("SubLayerGetByKey0", Native.FwpmSubLayerGetByKey0(handle, ref k, out o), o, 0x80320007); } }
        public bool ProviderExists() { Guid k = Plan.ProviderKey; IntPtr o; lock (gate) { return Exists("ProviderGetByKey0", Native.FwpmProviderGetByKey0(handle, ref k, out o), o, 0x80320005); } }
        public bool FilterExists(Guid key) { IntPtr o; lock (gate) { return Exists("FilterGetByKey0", Native.FwpmFilterGetByKey0(handle, ref key, out o), o, 0x80320003); } }
    }

    public sealed class LoopbackStub
    {
        TcpListener l; Thread t; volatile bool run;
        public static LoopbackStub Start(int port)
        {
            LoopbackStub s = new LoopbackStub(); s.l = new TcpListener(IPAddress.Loopback, port); s.l.Start(); s.run = true;
            s.t = new Thread(s.Loop); s.t.IsBackground = true; s.t.Start(); return s;
        }
        void Loop()
        {
            byte[] resp = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}");
            while (run)
            {
                try
                {
                    TcpClient c = l.AcceptTcpClient(); c.ReceiveTimeout = 2000;
                    try { NetworkStream s = c.GetStream(); byte[] buf = new byte[4096]; try { s.Read(buf, 0, buf.Length); } catch { } s.Write(resp, 0, resp.Length); } catch { }
                    c.Close();
                }
                catch { if (!run) break; }
            }
        }
        public void Stop() { run = false; try { l.Stop(); } catch { } }
    }
}
'@

function Initialize-WfpType {
    if (-not ('BlarAI.Wfp.Plan' -as [type])) { Add-Type -TypeDefinition $csharp -Language CSharp }
}

# ---------------------------------------------------------------------------------------------
# Pure helpers (no system change).
# ---------------------------------------------------------------------------------------------
function Test-SpikeArgs {
    # PURE. Returns an array of error strings (empty = valid).
    param([bool]$DryRun, [bool]$Live, [bool]$SelfTest, [int]$HoldSeconds, [string]$CoderUser)
    $e = New-Object System.Collections.ArrayList
    $modes = @($DryRun, $Live, $SelfTest) | Where-Object { $_ }
    if (@($modes).Count -ne 1) { [void]$e.Add('choose exactly one of -DryRun, -Live, -SelfTest') }
    if ($HoldSeconds -lt 1 -or $HoldSeconds -gt 120) { [void]$e.Add("HoldSeconds must be 1..120 (got $HoldSeconds)") }
    if ([string]::IsNullOrWhiteSpace($CoderUser) -or $CoderUser -notmatch '^[A-Za-z0-9._-]{1,20}$') { [void]$e.Add("CoderUser invalid: '$CoderUser'") }
    return @($e)
}

function Test-CoderSidSafe {
    # PURE. The block must never be able to match the operator: refuse unless the SID is an account-domain
    # user SID, is not the operator's own SID, and is not one of the operator token's group SIDs.
    param([string]$CoderSid, [string]$OperatorSid, [string[]]$OperatorGroupSids = @())
    $e = New-Object System.Collections.ArrayList
    if ($CoderSid -notmatch '^S-1-5-21-\d+-\d+-\d+-\d{3,}$') { [void]$e.Add("coder SID not an account-domain user SID: '$CoderSid'") }
    if ($CoderSid -eq $OperatorSid) { [void]$e.Add('coder SID equals the OPERATOR SID: the block would cut the operator off') }
    if ($OperatorGroupSids -contains $CoderSid) { [void]$e.Add('coder SID is a GROUP in the operator token') }
    return @($e)
}

function Get-SpikeExitCode {
    # PURE. Decision function. Precedence is safety-first: operator impact, then unverified removal,
    # then missing baseline, then inconclusive states, then the answer itself.
    param([Parameter(Mandatory)]$Obs)
    if ($Obs.OperatorAbort)                       { return [pscustomobject]@{ Code = 3; Reason = 'operator traffic affected (watchdog abort)' } }
    if (-not $Obs.RemovalVerified)                { return [pscustomobject]@{ Code = 7; Reason = 'removal NOT verified' } }
    if (-not $Obs.BaselineOk)                     { return [pscustomobject]@{ Code = 5; Reason = 'no baseline (operator offline or coder already blocked)' } }
    if ([int]$Obs.OperatorFailures -gt 0)         { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: isolated operator connect failure(s) during hold' } }
    if (-not $Obs.CoderProbeCompleted)            { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: no coder probe result while filters were live' } }
    if (-not $Obs.CoderSidIsCoder)                { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: probe did not run as the coder SID' } }
    if (-not $Obs.CoderOutboundBlocked)           { return [pscustomobject]@{ Code = 1; Reason = 'coder NOT blocked: raw WFP block did not enforce' } }
    if (-not $Obs.CoderLoopbackOk)                { return [pscustomobject]@{ Code = 4; Reason = 'coder blocked but loopback permit did not hold' } }
    return [pscustomobject]@{ Code = 0; Reason = 'coder blocked, loopback ok, operator unaffected, removal verified' }
}

function Test-TcpConnect {
    param([string]$Address, [int]$Port = 443, [int]$TimeoutMs = 5000)
    $sw = [Diagnostics.Stopwatch]::StartNew(); $c = New-Object Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect($Address, $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            try { $c.EndConnect($iar) } catch { return [pscustomobject]@{ target = "${Address}:$Port"; ok = $false; ms = $sw.ElapsedMilliseconds; error = $_.Exception.Message; t = (Get-Date).ToString('o') } }
            return [pscustomobject]@{ target = "${Address}:$Port"; ok = $true; ms = $sw.ElapsedMilliseconds; error = ''; t = (Get-Date).ToString('o') }
        }
        return [pscustomobject]@{ target = "${Address}:$Port"; ok = $false; ms = $sw.ElapsedMilliseconds; error = "timeout ${TimeoutMs}ms"; t = (Get-Date).ToString('o') }
    } catch {
        return [pscustomobject]@{ target = "${Address}:$Port"; ok = $false; ms = $sw.ElapsedMilliseconds; error = $_.Exception.Message; t = (Get-Date).ToString('o') }
    } finally { $c.Close() }
}

function Test-IsElevated {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-HexBlock {
    param([byte[]]$Bytes)
    $lines = for ($i = 0; $i -lt $Bytes.Length; $i += 16) {
        $n = [Math]::Min(16, $Bytes.Length - $i)
        ('  +{0:X4}: {1}' -f $i, (($Bytes[$i..($i + $n - 1)] | ForEach-Object { $_.ToString('X2') }) -join ' '))
    }
    $lines -join "`n"
}

# ---------------------------------------------------------------------------------------------
# -SelfTest
# ---------------------------------------------------------------------------------------------
function Invoke-SelfTest {
    Initialize-WfpType
    $script:st = @{ pass = 0; fail = 0 }
    function Assert-That([string]$Name, [bool]$Cond) {
        if ($Cond) { $script:st.pass++; Write-Host "  [PASS] $Name" -ForegroundColor Green }
        else { $script:st.fail++; Write-Host "  [FAIL] $Name" -ForegroundColor Red }
    }
    $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
    $other = 'S-1-5-21-1111111111-2222222222-3333333333-1002'
    Write-Host '== SelfTest: security descriptor ==' -ForegroundColor Cyan
    $plan = [BlarAI.Wfp.Plan]::Build($sid)
    $sd = New-Object Security.AccessControl.RawSecurityDescriptor($plan.Sd, 0)
    Assert-That 'DACL has exactly ONE ACE' ($sd.DiscretionaryAcl.Count -eq 1)
    $ace = $sd.DiscretionaryAcl[0]
    Assert-That 'ACE is ACCESS_ALLOWED' ($ace.AceQualifier -eq [Security.AccessControl.AceQualifier]::AccessAllowed)
    Assert-That 'ACE mask == FWP_ACTRL_MATCH_FILTER (0x1)' ($ace.AccessMask -eq 1)
    Assert-That 'ACE SID == coder SID only' ($ace.SecurityIdentifier.Value -eq $sid)
    Assert-That 'no other SID appears anywhere in the SD' ((($plan.Sddl -split 'S-1-') | Measure-Object).Count -eq 2)
    Assert-That 'owner and group are absent' (($null -eq $sd.Owner) -and ($null -eq $sd.Group))
    Assert-That "SDDL is exactly D:(A;;CC;;;$sid)" ($plan.Sddl -eq "D:(A;;CC;;;$sid)")
    Assert-That 'SD is self-relative (binary length matches blob)' ($plan.Sd.Length -eq $sd.BinaryLength)
    $plan2 = [BlarAI.Wfp.Plan]::Build($other)
    Assert-That 'a different coder SID yields a different SD (no hardcoded SID)' (($plan.Sddl -ne $plan2.Sddl) -and ($plan2.Sddl -notmatch '1001'))
    foreach ($bad in @('S-1-1-0', 'S-1-5-32-545', 'S-1-5-18', 'S-1-5-11', 'S-1-5-32-544', '', 'garbage', 'S-1-5-21-1-2-3-500x')) {
        $threw = $false; try { [void][BlarAI.Wfp.Plan]::Build($bad) } catch { $threw = $true }
        Assert-That "Plan.Build refuses '$bad'" $threw
    }

    Write-Host '== SelfTest: plan invariants ==' -ForegroundColor Cyan
    Assert-That 'four filters (permit+block on V4 and V6)' ($plan.Filters.Count -eq 4)
    $m = [BlarAI.Wfp.Marshalled]::Build($plan)
    try {
        $allUser = $true
        $condSize = [Runtime.InteropServices.Marshal]::SizeOf([type][BlarAI.Wfp.FWPM_FILTER_CONDITION0])
        for ($i = 0; $i -lt $m.Filters.Count; $i++) {
            $f = $m.Filters[$i]; $n = [int]$f.numFilterConditions
            $base = $f.filterCondition.ToInt64(); $has = $false
            for ($j = 0; $j -lt $n; $j++) {
                $c = [Runtime.InteropServices.Marshal]::PtrToStructure([IntPtr]($base + $j * $condSize), [type][BlarAI.Wfp.FWPM_FILTER_CONDITION0])
                if ($c.fieldKey -eq [BlarAI.Wfp.Plan]::CondAleUserId -and $c.conditionValue.type -eq 14 -and $c.matchType -eq 0) { $has = $true }
            }
            if (-not $has) { $allUser = $false }
        }
        Assert-That 'EVERY marshalled filter carries ALE_USER_ID / SECURITY_DESCRIPTOR / MATCH_EQUAL' $allUser
    } finally { $m.Free() }
    $permitW = ($plan.Filters | Where-Object { $_.Action -eq 0x1002 } | Select-Object -First 1).Weight
    $blockW = ($plan.Filters | Where-Object { $_.Action -eq 0x1001 } | Select-Object -First 1).Weight
    Assert-That 'permit weight > block weight' ($permitW -gt $blockW)
    Assert-That 'loopback condition only on PERMIT filters' (@($plan.Filters | Where-Object { $_.Loopback -and $_.Action -ne 0x1002 }).Count -eq 0)
    Assert-That 'layer GUIDs match fwpmu.h literals' (([BlarAI.Wfp.Plan]::LayerConnectV4 -eq [guid]'c38d57d1-05a7-4c33-904f-7fbceee60e82') -and ([BlarAI.Wfp.Plan]::LayerConnectV6 -eq [guid]'4a72393b-319f-44bc-84c3-ba54dcb3b6b4'))
    if ([Environment]::Is64BitProcess) {
        $M = [Runtime.InteropServices.Marshal]
        Assert-That 'x64 sizeof FWPM_FILTER0 == 200 (hand-derived from fwpmtypes.h)' ($M::SizeOf([type][BlarAI.Wfp.FWPM_FILTER0]) -eq 200)
        Assert-That 'x64 sizeof FWPM_FILTER_CONDITION0 == 40' ($M::SizeOf([type][BlarAI.Wfp.FWPM_FILTER_CONDITION0]) -eq 40)
        Assert-That 'x64 sizeof FWP_VALUE0 == 16' ($M::SizeOf([type][BlarAI.Wfp.FWP_VALUE0]) -eq 16)
        Assert-That 'x64 offsetof FWPM_FILTER0.weight == 96, .action == 128, .context == 152' (
            ($M::OffsetOf([type][BlarAI.Wfp.FWPM_FILTER0], 'weight').ToInt32() -eq 96) -and
            ($M::OffsetOf([type][BlarAI.Wfp.FWPM_FILTER0], 'action').ToInt32() -eq 128) -and
            ($M::OffsetOf([type][BlarAI.Wfp.FWPM_FILTER0], 'context').ToInt32() -eq 152))
    } else { Write-Host '  [SKIP] struct-size asserts need a 64-bit process' -ForegroundColor Yellow }

    Write-Host '== SelfTest: argument validation ==' -ForegroundColor Cyan
    Assert-That 'no mode -> error' ((Test-SpikeArgs $false $false $false 60 'blarai-coder').Count -ge 1)
    Assert-That 'two modes -> error' ((Test-SpikeArgs $true $true $false 60 'blarai-coder').Count -ge 1)
    Assert-That '-DryRun alone valid' ((Test-SpikeArgs $true $false $false 60 'blarai-coder').Count -eq 0)
    Assert-That '-Live alone valid' ((Test-SpikeArgs $false $true $false 120 'blarai-coder').Count -eq 0)
    Assert-That 'HoldSeconds 0 / 121 / -5 rejected' (((Test-SpikeArgs $false $true $false 0 'blarai-coder').Count -ge 1) -and ((Test-SpikeArgs $false $true $false 121 'blarai-coder').Count -ge 1) -and ((Test-SpikeArgs $false $true $false -5 'blarai-coder').Count -ge 1))
    Assert-That 'CoderUser with injection characters rejected' ((Test-SpikeArgs $false $true $false 60 'a;b').Count -ge 1)
    Assert-That 'SID safety: operator SID refused' ((Test-CoderSidSafe $sid $sid @()).Count -ge 1)
    Assert-That 'SID safety: group-in-operator-token refused' ((Test-CoderSidSafe $sid $other @($sid)).Count -ge 1)
    Assert-That 'SID safety: distinct account SID accepted' ((Test-CoderSidSafe $sid $other @('S-1-5-32-545')).Count -eq 0)
    Assert-That 'SID safety: Everyone refused' ((Test-CoderSidSafe 'S-1-1-0' $other @()).Count -ge 1)

    Write-Host '== SelfTest: exit-code decision (fabricated observations) ==' -ForegroundColor Cyan
    $good = @{ OperatorAbort = $false; RemovalVerified = $true; BaselineOk = $true; OperatorFailures = 0; CoderProbeCompleted = $true; CoderSidIsCoder = $true; CoderOutboundBlocked = $true; CoderLoopbackOk = $true }
    function Get-Variant($over) { $o = $good.Clone(); foreach ($k in $over.Keys) { $o[$k] = $over[$k] }; [pscustomobject]$o }
    Assert-That 'all good -> 0' ((Get-SpikeExitCode (Get-Variant @{})).Code -eq 0)
    Assert-That 'coder not blocked -> 1' ((Get-SpikeExitCode (Get-Variant @{ CoderOutboundBlocked = $false })).Code -eq 1)
    Assert-That 'operator abort -> 3 (even if everything else is good)' ((Get-SpikeExitCode (Get-Variant @{ OperatorAbort = $true })).Code -eq 3)
    Assert-That 'removal unverified beats "not blocked" -> 7' ((Get-SpikeExitCode (Get-Variant @{ RemovalVerified = $false; CoderOutboundBlocked = $false })).Code -eq 7)
    Assert-That 'no baseline -> 5' ((Get-SpikeExitCode (Get-Variant @{ BaselineOk = $false })).Code -eq 5)
    Assert-That 'isolated operator failure -> 4' ((Get-SpikeExitCode (Get-Variant @{ OperatorFailures = 1 })).Code -eq 4)
    Assert-That 'no coder result -> 4' ((Get-SpikeExitCode (Get-Variant @{ CoderProbeCompleted = $false })).Code -eq 4)
    Assert-That 'probe not the coder SID -> 4' ((Get-SpikeExitCode (Get-Variant @{ CoderSidIsCoder = $false })).Code -eq 4)
    Assert-That 'blocked but loopback failed -> 4' ((Get-SpikeExitCode (Get-Variant @{ CoderLoopbackOk = $false })).Code -eq 4)

    Write-Host ''
    Write-Host ("SelfTest: {0} passed, {1} failed" -f $script:st.pass, $script:st.fail) -ForegroundColor $(if ($script:st.fail -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:st.fail -eq 0) { 0 } else { 1 })
}

# ---------------------------------------------------------------------------------------------
# Environment/coder helpers (read-only unless stated)
# ---------------------------------------------------------------------------------------------
function Get-EnvSnapshot {
    $os = Get-CimInstance Win32_OperatingSystem
    $snap = [ordered]@{
        machine_clock = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')
        uptime_hours  = [Math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 2)
        os            = "$($os.Caption) $($os.Version)"
        ps_version    = $PSVersionTable.PSVersion.ToString()
        process_64bit = [Environment]::Is64BitProcess
        bitdefender_processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'bd|bitdefender|vsserv|epsecurity' } | Select-Object -ExpandProperty Name -Unique)
    }
    try { $snap.firewall_profiles = @(Get-NetFirewallProfile | ForEach-Object { [ordered]@{ name = [string]$_.Name; enabled = [string]$_.Enabled; default_outbound = [string]$_.DefaultOutboundAction } }) } catch { $snap.firewall_profiles = "error: $($_.Exception.Message)" }
    foreach ($svc in 'mpssvc', 'BFE') {
        try { $s = Get-Service $svc -ErrorAction Stop; $snap["svc_$svc"] = "$($s.Status)/$($s.StartType)" } catch { $snap["svc_$svc"] = "error: $($_.Exception.Message)" }
    }
    return $snap
}

function Resolve-CoderSid {
    # Same expression as verify-coder-containment.ps1 line 77.
    try { return (Get-LocalUser $CoderUser -ErrorAction Stop).SID.Value } catch { return $null }
}

function Get-OperatorTokenSids {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{ User = $id.User.Value; Groups = @($id.Groups | ForEach-Object { $_.Value }) }
}

function Invoke-ReadOnlyEngineCheck {
    # Opens the engine WITHOUT the dynamic flag and adds nothing; reports whether our objects exist.
    $e = [BlarAI.Wfp.Engine]::Open($false, 'BlarAI #1671 spike read-only check')
    try {
        $plan = [BlarAI.Wfp.Plan]::Build('S-1-5-21-1-2-3-1001')   # keys only; the SID is irrelevant to lookups
        $r = [ordered]@{ sublayer_present = $e.SubLayerExists(); provider_present = $e.ProviderExists() }
        $r.filters_present = @($plan.Filters | Where-Object { $e.FilterExists($_.Key) } | ForEach-Object { [string]$_.Key })
        return $r
    } finally { $e.Close() }
}

# --- coder probe through the scheduled-task path (same mechanism as verify-coder-containment.ps1) ---
function Start-CoderProbe {
    # Enqueue a 'probe' job + Start-ScheduledTask. Returns context for Receive/Wait. Never enqueues the dispatch kind.
    $jobId = Add-CoderLegJob -Job @{ kind = 'probe'; probe = @{ secret_paths = @(); loopback_url = $LoopbackUrl; expected_sid = $script:CoderSid } }
    $preRun = [datetime]'1999-11-30'
    try { $pr = (Get-ScheduledTaskInfo -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue).LastRunTime; if ($pr) { $preRun = $pr } } catch {}
    Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
    return [pscustomobject]@{ JobId = $jobId; PreRun = $preRun; Started = (Get-Date).ToString('o') }
}

function ConvertTo-ProbeObservation {
    param($Res, [string]$ExpectedSid)
    if ($null -eq $Res) { return [pscustomobject]@{ completed = $false } }
    $c = $Res.result.checks
    [pscustomobject]@{
        completed = $true; ran_as_sid = [string]$Res.ran_as_sid; sid_is_coder = ([string]$Res.ran_as_sid -eq $ExpectedSid)
        outbound_blocked = [bool]$c.outbound_blocked.pass; outbound_detail = [string]$c.outbound_blocked.detail
        loopback_ok = [bool]$c.loopback_ok.pass; loopback_detail = [string]$c.loopback_ok.detail
        secret_reads_denied = [bool]$c.secret_reads_denied.pass; t = (Get-Date).ToString('o')
    }
}

function Invoke-CoderProbeBlocking {
    # Start + prove-it-started + wait for the result. (The start-proof loop is the logic of verify-coder-containment.ps1
    # lines 127-152, which lives inside that script and cannot be dot-sourced; queue/wait helpers ARE reused.)
    param([int]$ResultTimeoutSec = 60)
    $ctx = Start-CoderProbe
    $started = $false; $lastResult = $null; $state = ''
    foreach ($i in 1..27) {
        Start-Sleep -Milliseconds 750
        $info = Get-ScheduledTaskInfo -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
        $state = [string](Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue).State
        if ($info) { $lastResult = $info.LastTaskResult }
        if (($info -and $info.LastRunTime -gt $ctx.PreRun) -or $state -eq 'Running') { $started = $true; break }
    }
    if (-not $started) {
        $hex = if ($null -ne $lastResult) { ('0x{0:X}' -f ([uint32]$lastResult)) } else { 'unknown' }
        return [pscustomobject]@{ completed = $false; error = "task never started (State=$state, LastTaskResult=$hex)" }
    }
    $res = Wait-CoderLegResult -JobId $ctx.JobId -TimeoutSec $ResultTimeoutSec
    $o = ConvertTo-ProbeObservation $res $script:CoderSid
    if (-not $o.completed) { $o | Add-Member -NotePropertyName error -NotePropertyValue "task started but no result within ${ResultTimeoutSec}s" -Force }
    return $o
}

# ---------------------------------------------------------------------------------------------
# -DryRun
# ---------------------------------------------------------------------------------------------
function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing is added; the engine is opened READ-ONLY (non-dynamic session, no Add calls) ==' -ForegroundColor Cyan
    Initialize-WfpType
    Write-Host 'C# compiled OK (Add-Type).' -ForegroundColor Green
    $sid = Resolve-CoderSid; $fabricated = $false
    if (-not $sid) { $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $fabricated = $true; Write-Host "coder account '$CoderUser' NOT FOUND: using a FABRICATED SID so the builders can still be exercised ($sid). -Live would exit 2." -ForegroundColor Yellow }
    else { Write-Host "coder SID (Get-LocalUser '$CoderUser', same expression as verify-coder-containment.ps1): $sid" }
    $op = Get-OperatorTokenSids
    $safety = Test-CoderSidSafe $sid $op.User $op.Groups
    Write-Host ("operator SID: {0}; SID safety: {1}" -f $op.User, $(if ($safety.Count -eq 0) { 'OK (distinct, not in operator token groups)' } else { 'REFUSED: ' + ($safety -join '; ') }))
    try {
        $rule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        if ($rule) { $sf = $rule | Get-NetFirewallSecurityFilter; Write-Host "existing (inert) firewall rule '$FirewallRuleName': LocalUser=$($sf.LocalUser)  (provision-coder-account.ps1 lines 325-326 build this as D:(A;;CC;;;<sid>))" }
        else { Write-Host "firewall rule '$FirewallRuleName' not present" }
    } catch { Write-Host "firewall rule lookup skipped: $($_.Exception.Message)" -ForegroundColor Yellow }
    $plan = [BlarAI.Wfp.Plan]::Build($sid)
    Write-Host ''; Write-Host $plan.Describe()
    $m = [BlarAI.Wfp.Marshalled]::Build($plan)
    try {
        Write-Host "-- serialised structs (this process is $(if ([Environment]::Is64BitProcess) {'64'} else {'32'})-bit; pointer fields hold run-specific addresses) --"
        Write-Host "FWPM_PROVIDER0 ($($m.ProviderImage.Length) bytes):"; Write-Host (ConvertTo-HexBlock $m.ProviderImage)
        Write-Host "FWPM_SUBLAYER0 ($($m.SubLayerImage.Length) bytes):"; Write-Host (ConvertTo-HexBlock $m.SubLayerImage)
        for ($i = 0; $i -lt $m.FilterImages.Count; $i++) { Write-Host "FWPM_FILTER0 [$i] $($plan.Filters[$i].Name) ($($m.FilterImages[$i].Length) bytes):"; Write-Host (ConvertTo-HexBlock $m.FilterImages[$i]) }
        for ($i = 0; $i -lt $m.CondImages.Count; $i++) { Write-Host "FWPM_FILTER_CONDITION0 [$i] ($($m.CondImages[$i].Length) bytes):"; Write-Host (ConvertTo-HexBlock $m.CondImages[$i]) }
    } finally { $m.Free() }
    Write-Host ''
    Write-Host '-- environment (read-only) --'
    (Get-EnvSnapshot) | ConvertTo-Json -Depth 5 | Write-Host
    Write-Host '-- coder-leg task (read-only) --'
    $t = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host $(if ($t) { "task $TaskPath$TaskName present, State=$($t.State)" } else { "task $TaskPath$TaskName NOT registered" })
    $paths = Get-CoderLegPaths; Write-Host "queue root (not touched): $($paths.Root)"
    Write-Host '-- BFE engine, read-only --'
    if (Test-IsElevated) {
        try { (Invoke-ReadOnlyEngineCheck) | ConvertTo-Json | Write-Host; Write-Host 'FwpmEngineOpen0 + sublayer/provider/filter lookups work; our objects are absent as expected.' -ForegroundColor Green }
        catch { Write-Host "engine read-only check FAILED: $($_.Exception.Message)" -ForegroundColor Red; return 4 }
    } else { Write-Host 'SKIPPED: not elevated (FwpmEngineOpen0 + lookups need elevation). -Live would exit 2.' -ForegroundColor Yellow }
    Write-Host ''
    Write-Host 'DRY RUN complete. Nothing was added.' -ForegroundColor Green
    if ($fabricated) { return 2 }
    return 0
}

# ---------------------------------------------------------------------------------------------
# -Live
# ---------------------------------------------------------------------------------------------
function Invoke-Live {
    $report = [ordered]@{ spike = '#1671 raw WFP block keyed to the coder account'; started = (Get-Date).ToString('o'); env = (Get-EnvSnapshot); hold_seconds = $HoldSeconds; steps = [ordered]@{} }
    $obs = @{ OperatorAbort = $false; RemovalVerified = $false; BaselineOk = $false; OperatorFailures = 0; CoderProbeCompleted = $false; CoderSidIsCoder = $false; CoderOutboundBlocked = $false; CoderLoopbackOk = $false }
    $engine = $null; $stub = $null; $code = 4; $reason = 'error before decision'; $saved = $false
    function Save-Report {
        param([int]$Code, [string]$Reason)
        $report.finished = (Get-Date).ToString('o'); $report.exit_code = $Code; $report.exit_reason = $Reason; $report.decision_inputs = $obs
        $report.answer = switch ($Code) { 0 { 'RAW WFP BLOCK ENFORCES for the coder account under Bitdefender (loopback preserved, operator unaffected).' } 1 { 'RAW WFP does NOT enforce under Bitdefender (coder egress stayed open with the block live).' } default { "no answer ($Reason)" } }
        New-Item -ItemType Directory -Force $OutDir | Out-Null
        $p = Join-Path $OutDir ("result-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        ($report | ConvertTo-Json -Depth 12) | Set-Content -Path $p -Encoding UTF8
        Write-Host "report: $p" -ForegroundColor Cyan
    }
    try {
        # 0 preflight -------------------------------------------------------------------------
        Write-Host '== 0 preflight ==' -ForegroundColor Cyan
        if (-not (Test-IsElevated)) { Write-Host 'FAIL: not elevated.' -ForegroundColor Red; return 2 }
        if (-not [Environment]::Is64BitProcess) { Write-Host 'FAIL: run in a 64-bit PowerShell (struct layout asserted for x64).' -ForegroundColor Red; return 2 }
        Initialize-WfpType
        $script:CoderSid = Resolve-CoderSid
        if (-not $script:CoderSid) { Write-Host "FAIL: coder account '$CoderUser' not found." -ForegroundColor Red; return 2 }
        $op = Get-OperatorTokenSids
        $safety = Test-CoderSidSafe $script:CoderSid $op.User $op.Groups
        if ($safety.Count) { Write-Host ('FAIL: ' + ($safety -join '; ')) -ForegroundColor Red; return 2 }
        if (-not (Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue)) { Write-Host "FAIL: task $TaskPath$TaskName not registered." -ForegroundColor Red; return 2 }
        $pre = Invoke-ReadOnlyEngineCheck
        if ($pre.sublayer_present -or $pre.provider_present -or $pre.filters_present.Count) { Write-Host 'FAIL: our sublayer/provider/filters already exist (stale state). Nothing added.' -ForegroundColor Red; return 2 }
        $plan = [BlarAI.Wfp.Plan]::Build($script:CoderSid)
        $report.steps.preflight = [ordered]@{ coder_sid = $script:CoderSid; operator_sid = $op.User; sd_sddl = $plan.Sddl; objects_absent_before = $true }
        Write-Host "coder SID $($script:CoderSid); SD $($plan.Sddl)"
        Write-Host 'ROLLBACK FACT: every object lives in a DYNAMIC WFP session. Closing the engine handle OR this process exiting/dying removes provider, sublayer and all filters. Nothing is persistent. Backstop: a timer thread closes the handle after HoldSeconds+30 s.' -ForegroundColor Yellow
        $up = $false; try { $c = New-Object Net.Sockets.TcpClient; $iar = $c.BeginConnect('127.0.0.1', 8000, $null, $null); $up = ($iar.AsyncWaitHandle.WaitOne(1000, $false) -and $c.Connected); $c.Close() } catch { $up = $false }
        if (-not $up) { $stub = [BlarAI.Wfp.LoopbackStub]::Start(8000); Write-Host 'loopback stub started on 127.0.0.1:8000 (nothing was listening; stopped in finally)' }
        else { Write-Host 'something already listens on 127.0.0.1:8000: using it for the coder loopback check' }
        $report.steps.preflight.loopback_stub_started = [bool]$stub

        # 1 control -------------------------------------------------------------------------
        Write-Host '== 1 control / baseline ==' -ForegroundColor Cyan
        $ctl = @(); foreach ($i in 1..3) { foreach ($t in '1.1.1.1', '8.8.8.8') { $ctl += Test-TcpConnect $t 443 5000 } }
        $report.steps.operator_baseline = $ctl
        if (@($ctl | Where-Object { -not $_.ok }).Count) { Write-Host 'operator baseline failed; aborting (no baseline).' -ForegroundColor Red; $code = 5; $reason = 'no baseline: operator cannot reach the internet'; Save-Report $code $reason; $saved = $true; return $code }
        Write-Host 'operator baseline: 6/6 connects OK'
        $base = Invoke-CoderProbeBlocking
        $report.steps.coder_baseline = $base
        if (-not $base.completed -or -not $base.sid_is_coder) { Write-Host "coder baseline unusable: $($base.error)" -ForegroundColor Red; $code = 5; $reason = 'no baseline: coder probe did not complete as the coder'; Save-Report $code $reason; $saved = $true; return $code }
        Write-Host "coder baseline: outbound_blocked.pass=$($base.outbound_blocked) (expected False = egress open today), loopback_ok=$($base.loopback_ok)"
        if ($base.outbound_blocked) { Write-Host 'coder egress ALREADY blocked before our filters: spike uninformative.' -ForegroundColor Red; $code = 5; $reason = 'no baseline: coder already blocked'; Save-Report $code $reason; $saved = $true; return $code }
        $obs.BaselineOk = $true

        # 2 add filters (one transaction) ---------------------------------------------------
        Write-Host '== 2 add filters ==' -ForegroundColor Cyan
        $engine = [BlarAI.Wfp.Engine]::Open($true, 'BlarAI #1671 spike (dynamic)')
        $engine.ArmDeadMan($HoldSeconds + 30)
        $ids = $engine.AddAll($plan)
        $report.steps.filters_added = [ordered]@{ at = (Get-Date).ToString('o'); filter_ids = @($ids); filters = @($plan.Filters | ForEach-Object { "$($_.Name) $($_.Key)" }) }
        Write-Host "added in ONE transaction: filter ids $($ids -join ', ')" -ForegroundColor Yellow

        # 3+4 hold: watchdog + coder probe -------------------------------------------------
        Write-Host '== 3/4 hold (watchdog every 2 s; coder probe via task) ==' -ForegroundColor Cyan
        $ctx = Start-CoderProbe
        $deadline = (Get-Date).AddSeconds($HoldSeconds); $consec = 0; $watch = @(); $coderRes = $null
        $resPath = Join-Path (Get-CoderLegPaths).Results "$($ctx.JobId).result.json"
        while ((Get-Date) -lt $deadline) {
            $w = Test-TcpConnect '1.1.1.1' 443 2000; $watch += $w
            if ($w.ok) { $consec = 0 } else { $consec++; $obs.OperatorFailures++ }
            if ($consec -ge 2) {
                $engine.Close(); $obs.OperatorAbort = $true
                Write-Host 'OPERATOR TRAFFIC AFFECTED: two consecutive failures. Engine closed, everything removed.' -ForegroundColor Red
                break
            }
            if (-not $coderRes -and (Test-Path $resPath)) { $coderRes = Wait-CoderLegResult -JobId $ctx.JobId -TimeoutSec 3 -PollSec 1 }
            if ($coderRes -and $watch.Count -ge 3) { break }
            Start-Sleep -Milliseconds 1500
        }
        $report.steps.watchdog = $watch
        if (-not $obs.OperatorAbort) {
            $report.steps.operator_during = @((Test-TcpConnect '1.1.1.1' 443 3000), (Test-TcpConnect '8.8.8.8' 443 3000))
            foreach ($d in $report.steps.operator_during) { if (-not $d.ok) { $obs.OperatorFailures++ } }
            if (-not $coderRes -and (Test-Path $resPath)) { $coderRes = Wait-CoderLegResult -JobId $ctx.JobId -TimeoutSec 3 -PollSec 1 }
        }
        $during = ConvertTo-ProbeObservation $coderRes $script:CoderSid
        if (-not $during.completed) {
            $info = Get-ScheduledTaskInfo -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
            $during | Add-Member -NotePropertyName error -NotePropertyValue ("no coder result within hold; task LastTaskResult=" + $(if ($info) { '0x{0:X}' -f ([uint32]$info.LastTaskResult) } else { 'unknown' })) -Force
        }
        $report.steps.coder_during = $during
        $obs.CoderProbeCompleted = [bool]$during.completed
        if ($during.completed) { $obs.CoderSidIsCoder = [bool]$during.sid_is_coder; $obs.CoderOutboundBlocked = [bool]$during.outbound_blocked; $obs.CoderLoopbackOk = [bool]$during.loopback_ok }
        Write-Host "coder during: completed=$($during.completed) outbound_blocked=$($during.outbound_blocked) loopback_ok=$($during.loopback_ok) sid_is_coder=$($during.sid_is_coder)"

        # 5 close + verify removal --------------------------------------------------------
        Write-Host '== 5 close engine + verify removal ==' -ForegroundColor Cyan
        $engine.Close()
        $report.steps.engine_close_status = ('0x{0:X8}' -f $engine.LastCloseStatus)
        $post = Invoke-ReadOnlyEngineCheck
        $report.steps.removal_engine_check = $post
        $engineGone = (-not $post.sublayer_present) -and (-not $post.provider_present) -and ($post.filters_present.Count -eq 0)
        $after = $null
        if (-not $obs.OperatorAbort) {
            $after = Invoke-CoderProbeBlocking
            $report.steps.coder_after_removal = $after
        }
        $egressReopened = $true
        if ($after) { $egressReopened = ($after.completed -and (-not $after.outbound_blocked)) }
        $obs.RemovalVerified = ($engineGone -and $egressReopened)
        Write-Host "removal: engine objects gone=$engineGone; coder egress open again=$egressReopened"
        $d = Get-SpikeExitCode ([pscustomobject]$obs)
        $code = $d.Code; $reason = $d.Reason
    } catch {
        $report.error = $_.Exception.Message + ' @ ' + $_.InvocationInfo.PositionMessage
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        $code = 4; $reason = 'error: ' + $_.Exception.Message
    } finally {
        if ($engine) { $engine.Close() }          # idempotent; the dynamic session is the backstop
        if ($stub) { $stub.Stop() }
    }
    if (-not $saved) {
        if ($report.Contains('error')) {
            # Error path: verify removal anyway so a failure is never reported without it.
            try { $post2 = Invoke-ReadOnlyEngineCheck; $report.steps.final_removal_check = $post2; if ($post2.sublayer_present -or $post2.filters_present.Count) { $code = 7; $reason = 'removal NOT verified after error' } } catch { $report.steps.final_removal_check = "error: $($_.Exception.Message)"; $code = 7; $reason = 'removal NOT verifiable after error' }
        }
        Save-Report $code $reason
    }
    Write-Host ("RESULT: exit {0}: {1}" -f $code, $reason) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Yellow' })
    return $code
}

# ---------------------------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------------------------
$argErrors = Test-SpikeArgs $DryRun.IsPresent $Live.IsPresent $SelfTest.IsPresent $HoldSeconds $CoderUser
if ($argErrors.Count) { $argErrors | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; exit 2 }
if (-not $SelfTest) {
    foreach ($f in 'coder-leg-queue.ps1', 'coder-provisioning-lib.ps1') {
        $p = Join-Path $AgenticScripts $f
        if (-not (Test-Path $p)) { Write-Host "missing helper $p" -ForegroundColor Red; exit 2 }
        . $p      # dot-source: reuse the agentic-setup helpers (no side effects on load)
    }
}
if ($SelfTest) { exit (Invoke-SelfTest) }
if ($DryRun) { exit (Invoke-DryRun) }
if ($Live) {
    if (-not (Test-IsElevated)) { Write-Host 'FAIL: -Live requires an elevated shell.' -ForegroundColor Red; exit 2 }
    exit (Invoke-Live)
}
