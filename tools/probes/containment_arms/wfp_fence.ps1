#requires -Version 7.0
<#
.SYNOPSIS
  #1740 phase 2: a temporary Windows Filtering Platform (WFP) egress fence keyed to ONE identity,
  so a containment setup's outbound connections can be tested with the lock on and off.

.DESCRIPTION
  Derived from the #1671 spike (docs/research/containment-evidence-2026-10-05/wfp-spike/
  wfp-coder-egress-spike.ps1): the struct definitions are copied verbatim from it; the plan
  builder takes an identity kind instead of the coder account.

  Identity kinds:
    discriminate  app-scoped separation test for restricted tokens (see below).
    user     FWPM_CONDITION_ALE_USER_ID with a one-ACE security descriptor naming -TargetSid.
             WFP evaluates it as an access check against the connecting process's token.
             Accepted: an account-domain user SID (S-1-5-21-...-RID) or a synthetic S-1-5-80
             SID (the restricting SID of the write-restricted setup).
    package  FWPM_CONDITION_ALE_PACKAGE_ID (FWP_SID) equal to -TargetSid, an AppContainer
             package SID (S-1-15-2-...).
  Every filter carries the identity condition; permits for loopback outrank the blocks.

  discriminate (needs -AllowOperatorSid, -SyntheticSid and -AppPath):
    Asks whether WFP evaluates a token's restricting SIDs. Every filter is scoped to ONE program file
    (ALE_APP_ID == -AppPath, which must be a file under C:\blarai-spike-1740\), so no other program on the
    machine, including the operator's own tools, can match any filter whatever the identity conditions do.
      block   : ALE_USER_ID SD naming the operator AND the synthetic SID  + that program
      permit  : (-Variant block-permit only) ALE_USER_ID SD naming the operator alone + that program, outranking
                the block; a normally logged-on operator token matches both, a token whose restricting list
                holds neither the operator nor a matching entry fails the permit only
      loopback: permit for loopback + that program, so only non-loopback traffic is tested
    -Variant block-only is the positive control: it shows the block engages at all.
  -TargetSid is refused if it is the operator's own SID or any group in the operator's token.

  Modes (exactly one):
    -SelfTest   pure helpers only: SD builder, SID gates, struct sizes. No system change.
    -DryRun     compile, build the plan, open the engine READ-ONLY, report whether our objects exist.
    -Hold       elevated. Add the filters in ONE transaction through a DYNAMIC session (the kernel
                removes everything when the handle closes or this process dies), write
                <MarkerDir>\ARMED, hold until <MarkerDir>\DONE appears or -HoldSeconds pass, with an
                operator watchdog (1.1.1.1:443 every 2 s; two consecutive failures close the engine
                at once), then close, verify every object is gone and write <MarkerDir>\fence.json.

  EXIT CODES
    0 held and removed, operator unaffected   2 precondition / argument failure (nothing added)
    3 operator traffic affected (removed)     4 error            7 removal NOT verified
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$DryRun,
    [switch]$Hold,
    [ValidateSet('user', 'package', 'discriminate')][string]$Kind = 'user',
    [string]$TargetSid = '',
    [ValidateSet('block-only', 'block-permit')][string]$Variant = 'block-permit',
    [string]$SyntheticSid = '',
    [string]$AppPath = '',
    [switch]$AllowOperatorSid,
    [int]$HoldSeconds = 120,
    [string]$MarkerDir = 'C:\blarai-spike-1740\fence'
)
$ErrorActionPreference = 'Stop'

$csharp = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.RegularExpressions;
using System.Threading;

namespace BlarAI.Wfp1740
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
        [DllImport("fwpuclnt.dll", CharSet = CharSet.Unicode)] public static extern uint FwpmGetAppIdFromFileName0(string fileName, out IntPtr appId);
    }

    public class FilterSpec
    {
        public Guid Key; public string Name; public Guid Layer; public uint Action; public ulong Weight; public bool Loopback;
        public string IdentityKind = "none"; public byte[] IdentityValue; public string AppPath;
    }

    public sealed class Plan
    {
        // From the installed Windows SDK 10.0.26100.0: um/fwpmu.h (layers, ALE_USER_ID, ALE_PACKAGE_ID, FLAGS)
        // and shared/fwptypes.h (FWP_SID = 13, FWP_SECURITY_DESCRIPTOR_TYPE = 14), read 2026-10-10.
        public static readonly Guid LayerConnectV4   = new Guid("c38d57d1-05a7-4c33-904f-7fbceee60e82");
        public static readonly Guid LayerConnectV6   = new Guid("4a72393b-319f-44bc-84c3-ba54dcb3b6b4");
        public static readonly Guid CondAleUserId    = new Guid("af043a0a-b34d-4f86-979c-c90371af6e66");
        public static readonly Guid CondAlePackageId = new Guid("71bc78fa-f17c-4997-a602-6abb261f351c");
        public static readonly Guid CondFlags        = new Guid("632ce23b-5167-435c-86d7-e903684aa80c");
        public static readonly Guid CondAleAppId     = new Guid("d78e1e87-8644-4ea5-9437-d809ecefc971");
        // Our own keys for #1740 (distinct from the #1671 spike's).
        public static readonly Guid ProviderKey = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e1741");
        public static readonly Guid SubLayerKey = new Guid("7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e1742");
        public const uint FWP_UINT32 = 3, FWP_UINT64 = 4, FWP_BYTE_BLOB_TYPE = 12, FWP_SID = 13, FWP_SECURITY_DESCRIPTOR_TYPE = 14;
        public const uint FWP_MATCH_EQUAL = 0, FWP_MATCH_FLAGS_ALL_SET = 6;
        public const uint FWP_ACTION_BLOCK = 0x1001, FWP_ACTION_PERMIT = 0x1002;
        public const uint FWP_CONDITION_FLAG_IS_LOOPBACK = 1, FWP_ACTRL_MATCH_FILTER = 1;
        public const uint FWPM_SESSION_FLAG_DYNAMIC = 1;
        public const ushort SubLayerWeight = 0xFFFF;
        public const ulong PermitWeight = 0x2000, BlockWeight = 0x1000;

        public string Kind; public string TargetSid; public byte[] Value; public string Describe;
        public List<FilterSpec> Filters = new List<FilterSpec>();

        public static bool IsAcceptable(string kind, string sid)
        {
            if (sid == null) return false;
            if (kind == "user") return Regex.IsMatch(sid, @"^S-1-5-21-\d+-\d+-\d+-\d{3,}$") || Regex.IsMatch(sid, @"^S-1-5-80(-\d+){5}$");
            if (kind == "package") return Regex.IsMatch(sid, @"^S-1-15-2(-\d+){7}$");
            return false;
        }

        public static byte[] BuildSd(params string[] sids)
        {
            RawAcl acl = new RawAcl(2, sids.Length);
            for (int i = 0; i < sids.Length; i++)
                acl.InsertAce(i, new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, (int)FWP_ACTRL_MATCH_FILTER, new SecurityIdentifier(sids[i]), false, null));
            RawSecurityDescriptor sd = new RawSecurityDescriptor(ControlFlags.DiscretionaryAclPresent, null, null, null, acl);
            byte[] b = new byte[sd.BinaryLength]; sd.GetBinaryForm(b, 0); return b;
        }

        public const string AppRoot = "C:\\blarai-spike-1740\\";

        public static bool IsAcceptableAppPath(string path)
        {
            if (string.IsNullOrEmpty(path)) return false;
            string full;
            try { full = System.IO.Path.GetFullPath(path); } catch { return false; }
            if (!(full.StartsWith(AppRoot, StringComparison.OrdinalIgnoreCase) && full.IndexOf("..", StringComparison.Ordinal) < 0
                && System.IO.File.Exists(full) && (System.IO.File.GetAttributes(full) & System.IO.FileAttributes.ReparsePoint) == 0)) return false;
            // A junction in any parent folder would make the filter match the junction's target program.
            for (string dir = System.IO.Path.GetDirectoryName(full); !string.IsNullOrEmpty(dir) && dir.Length >= AppRoot.TrimEnd((char)92).Length; dir = System.IO.Path.GetDirectoryName(dir))
            {
                if ((System.IO.File.GetAttributes(dir) & System.IO.FileAttributes.ReparsePoint) != 0) return false;
            }
            return true;
        }

        // The app-scoped separation test. Every filter names one program file; see the script header.
        public static Plan BuildDiscriminate(string operatorSid, string syntheticSid, string appPath, bool withPermit)
        {
            if (!IsAcceptable("user", operatorSid)) throw new ArgumentException("refusing operator SID: " + operatorSid);
            if (!IsAcceptable("user", syntheticSid) || syntheticSid == operatorSid) throw new ArgumentException("refusing synthetic SID: " + syntheticSid);
            if (!IsAcceptableAppPath(appPath)) throw new ArgumentException("refusing app path (must be an existing non-link file under " + AppRoot + "): " + appPath);
            Plan p = new Plan(); p.Kind = "discriminate"; p.TargetSid = operatorSid + "+" + syntheticSid;
            string full = System.IO.Path.GetFullPath(appPath);
            byte[] blockSd = BuildSd(operatorSid, syntheticSid);
            byte[] permitSd = BuildSd(operatorSid);
            p.Describe = "app " + full + "; block SD " + new RawSecurityDescriptor(blockSd, 0).GetSddlForm(AccessControlSections.Access)
                + (withPermit ? "; permit SD " + new RawSecurityDescriptor(permitSd, 0).GetSddlForm(AccessControlSections.Access) : "; no permit");
            p.Filters.Add(Spec(Mk("f1740001-0000-4d8e-9a31-2b6d4c8e1f11", "permit-loopback-app-v4", LayerConnectV4, FWP_ACTION_PERMIT, PermitWeight, true), "none", null, full));
            p.Filters.Add(Spec(Mk("f1740002-0000-4d8e-9a31-2b6d4c8e1f12", "permit-loopback-app-v6", LayerConnectV6, FWP_ACTION_PERMIT, PermitWeight, true), "none", null, full));
            p.Filters.Add(Spec(Mk("f1740003-0000-4d8e-9a31-2b6d4c8e1f21", "block-app-v4", LayerConnectV4, FWP_ACTION_BLOCK, BlockWeight, false), "user", blockSd, full));
            p.Filters.Add(Spec(Mk("f1740004-0000-4d8e-9a31-2b6d4c8e1f22", "block-app-v6", LayerConnectV6, FWP_ACTION_BLOCK, BlockWeight, false), "user", blockSd, full));
            if (withPermit)
            {
                p.Filters.Add(Spec(Mk("f1740005-0000-4d8e-9a31-2b6d4c8e1f31", "permit-operator-app-v4", LayerConnectV4, FWP_ACTION_PERMIT, PermitWeight, false), "user", permitSd, full));
                p.Filters.Add(Spec(Mk("f1740006-0000-4d8e-9a31-2b6d4c8e1f32", "permit-operator-app-v6", LayerConnectV6, FWP_ACTION_PERMIT, PermitWeight, false), "user", permitSd, full));
            }
            return p;
        }

        static FilterSpec Spec(FilterSpec f, string kind, byte[] value, string appPath) { f.IdentityKind = kind; f.IdentityValue = value; f.AppPath = appPath; return f; }

        public static Plan Build(string kind, string sid)
        {
            if (!IsAcceptable(kind, sid)) throw new ArgumentException("refusing " + kind + " SID: " + sid);
            Plan p = new Plan(); p.Kind = kind; p.TargetSid = sid;
            if (kind == "user")
            {
                p.Value = BuildSd(sid);
                p.Describe = "ALE_USER_ID SD " + new RawSecurityDescriptor(p.Value, 0).GetSddlForm(AccessControlSections.Access);
            }
            else
            {
                SecurityIdentifier si = new SecurityIdentifier(sid);
                p.Value = new byte[si.BinaryLength]; si.GetBinaryForm(p.Value, 0);
                p.Describe = "ALE_PACKAGE_ID == " + sid;
            }
            p.Filters.Add(Mk("f1740001-0000-4d8e-9a31-2b6d4c8e1f11", "permit-loopback-v4", LayerConnectV4, FWP_ACTION_PERMIT, PermitWeight, true));
            p.Filters.Add(Mk("f1740002-0000-4d8e-9a31-2b6d4c8e1f12", "permit-loopback-v6", LayerConnectV6, FWP_ACTION_PERMIT, PermitWeight, true));
            p.Filters.Add(Mk("f1740003-0000-4d8e-9a31-2b6d4c8e1f21", "block-v4", LayerConnectV4, FWP_ACTION_BLOCK, BlockWeight, false));
            p.Filters.Add(Mk("f1740004-0000-4d8e-9a31-2b6d4c8e1f22", "block-v6", LayerConnectV6, FWP_ACTION_BLOCK, BlockWeight, false));
            foreach (FilterSpec f in p.Filters) { f.IdentityKind = kind; f.IdentityValue = p.Value; }
            return p;
        }

        static FilterSpec Mk(string key, string name, Guid layer, uint action, ulong weight, bool loop)
        {
            FilterSpec f = new FilterSpec(); f.Key = new Guid(key); f.Name = "BlarAI #1740 fence: " + name;
            f.Layer = layer; f.Action = action; f.Weight = weight; f.Loopback = loop; return f;
        }
    }

    public sealed class Marshalled
    {
        public List<IntPtr> Allocs = new List<IntPtr>(); public List<IntPtr> AppIds = new List<IntPtr>();
        public FWPM_PROVIDER0 Provider; public FWPM_SUBLAYER0 SubLayer; public List<FWPM_FILTER0> Filters = new List<FWPM_FILTER0>();
        IntPtr A(int n) { IntPtr p = Marshal.AllocHGlobal(n); Allocs.Add(p); return p; }
        IntPtr Str(string s) { IntPtr p = Marshal.StringToHGlobalUni(s); Allocs.Add(p); return p; }
        FWPM_DISPLAY_DATA0 DD(string n) { FWPM_DISPLAY_DATA0 x = new FWPM_DISPLAY_DATA0(); x.name = Str(n); x.description = Str("Temporary dynamic object; removed when the engine handle closes."); return x; }

        public static Marshalled Build(Plan plan)
        {
            Marshalled m = new Marshalled();
            IntPtr provKey = m.A(16); Marshal.StructureToPtr(Plan.ProviderKey, provKey, false);
            m.Provider.providerKey = Plan.ProviderKey; m.Provider.displayData = m.DD("BlarAI #1740 fence provider");
            m.SubLayer.subLayerKey = Plan.SubLayerKey; m.SubLayer.providerKey = provKey;
            m.SubLayer.displayData = m.DD("BlarAI #1740 fence sublayer"); m.SubLayer.weight = Plan.SubLayerWeight;
            int condSize = Marshal.SizeOf(typeof(FWPM_FILTER_CONDITION0));
            foreach (FilterSpec f in plan.Filters)
            {
                List<FWPM_FILTER_CONDITION0> conds = new List<FWPM_FILTER_CONDITION0>();
                if (f.Loopback)
                {
                    FWPM_FILTER_CONDITION0 c = new FWPM_FILTER_CONDITION0(); c.fieldKey = Plan.CondFlags; c.matchType = Plan.FWP_MATCH_FLAGS_ALL_SET;
                    c.conditionValue.type = Plan.FWP_UINT32; c.conditionValue.value = new IntPtr((int)Plan.FWP_CONDITION_FLAG_IS_LOOPBACK); conds.Add(c);
                }
                if (f.IdentityKind != "none")
                {
                    IntPtr valueData = m.A(f.IdentityValue.Length); Marshal.Copy(f.IdentityValue, 0, valueData, f.IdentityValue.Length);
                    IntPtr valuePtr = valueData;
                    if (f.IdentityKind == "user")
                    {   // FWP_SECURITY_DESCRIPTOR_TYPE takes an FWP_BYTE_BLOB*.
                        FWP_BYTE_BLOB blob = new FWP_BYTE_BLOB(); blob.size = (uint)f.IdentityValue.Length; blob.data = valueData;
                        valuePtr = m.A(Marshal.SizeOf(typeof(FWP_BYTE_BLOB))); Marshal.StructureToPtr(blob, valuePtr, false);
                    }   // FWP_SID takes a SID* directly.
                    FWPM_FILTER_CONDITION0 u = new FWPM_FILTER_CONDITION0();
                    u.fieldKey = f.IdentityKind == "user" ? Plan.CondAleUserId : Plan.CondAlePackageId; u.matchType = Plan.FWP_MATCH_EQUAL;
                    u.conditionValue.type = f.IdentityKind == "user" ? Plan.FWP_SECURITY_DESCRIPTOR_TYPE : Plan.FWP_SID; u.conditionValue.value = valuePtr; conds.Add(u);
                }
                if (f.AppPath != null)
                {   // FWP_BYTE_BLOB_TYPE takes an FWP_BYTE_BLOB* (the NT path from FwpmGetAppIdFromFileName0).
                    IntPtr appId; uint arc = Native.FwpmGetAppIdFromFileName0(f.AppPath, out appId);
                    if (arc != 0) throw new InvalidOperationException("FwpmGetAppIdFromFileName0 failed 0x" + arc.ToString("X8") + " for " + f.AppPath);
                    m.AppIds.Add(appId);
                    FWPM_FILTER_CONDITION0 a = new FWPM_FILTER_CONDITION0(); a.fieldKey = Plan.CondAleAppId; a.matchType = Plan.FWP_MATCH_EQUAL;
                    a.conditionValue.type = Plan.FWP_BYTE_BLOB_TYPE; a.conditionValue.value = appId; conds.Add(a);
                }
                if (f.IdentityKind == "none" && f.AppPath == null) throw new InvalidOperationException("refusing an unscoped filter: " + f.Name);
                IntPtr arr = m.A(condSize * conds.Count);
                for (int i = 0; i < conds.Count; i++) Marshal.StructureToPtr(conds[i], new IntPtr(arr.ToInt64() + (long)i * condSize), false);
                FWPM_FILTER0 fl = new FWPM_FILTER0(); fl.filterKey = f.Key; fl.displayData = m.DD(f.Name);
                fl.providerKey = provKey; fl.layerKey = f.Layer; fl.subLayerKey = Plan.SubLayerKey;
                fl.weight.type = Plan.FWP_UINT64; IntPtr w = m.A(8); Marshal.WriteInt64(w, unchecked((long)f.Weight)); fl.weight.value = w;
                fl.numFilterConditions = (uint)conds.Count; fl.filterCondition = arr; fl.action.type = f.Action;
                m.Filters.Add(fl);
            }
            return m;
        }
        public void Free() { foreach (IntPtr p in Allocs) Marshal.FreeHGlobal(p); Allocs.Clear(); foreach (IntPtr a in AppIds) { IntPtr t = a; Native.FwpmFreeMemory0(ref t); } AppIds.Clear(); }
    }

    public sealed class Engine
    {
        IntPtr handle; readonly object gate = new object(); Timer deadMan; public uint LastCloseStatus;
        public static Engine Open(bool dynamicSession, string name)
        {
            FWPM_SESSION0 s = new FWPM_SESSION0(); IntPtr nm = Marshal.StringToHGlobalUni(name);
            try
            {
                s.displayData.name = nm; s.flags = dynamicSession ? Plan.FWPM_SESSION_FLAG_DYNAMIC : 0; s.txnWaitTimeoutInMSec = 10000;
                IntPtr h; uint rc = Native.FwpmEngineOpen0(null, 0xFFFFFFFF, IntPtr.Zero, ref s, out h);
                if (rc != 0) throw new InvalidOperationException("FwpmEngineOpen0 failed 0x" + rc.ToString("X8"));
                Engine e = new Engine(); e.handle = h; return e;
            }
            finally { Marshal.FreeHGlobal(nm); }
        }
        public void ArmDeadMan(int seconds) { deadMan = new Timer(delegate(object o) { Close(); }, null, seconds * 1000, Timeout.Infinite); }
        public void Close() { lock (gate) { if (handle == IntPtr.Zero) return; LastCloseStatus = Native.FwpmEngineClose0(handle); handle = IntPtr.Zero; } }
        static void Check(string what, uint rc) { if (rc != 0) throw new InvalidOperationException(what + " failed 0x" + rc.ToString("X8")); }
        public ulong[] AddAll(Plan plan)
        {
            Marshalled m = Marshalled.Build(plan); bool inTxn = false; List<ulong> ids = new List<ulong>();
            try
            {
                lock (gate)
                {
                    Check("FwpmTransactionBegin0", Native.FwpmTransactionBegin0(handle, 0)); inTxn = true;
                    FWPM_PROVIDER0 p = m.Provider; Check("FwpmProviderAdd0", Native.FwpmProviderAdd0(handle, ref p, IntPtr.Zero));
                    FWPM_SUBLAYER0 sl = m.SubLayer; Check("FwpmSubLayerAdd0", Native.FwpmSubLayerAdd0(handle, ref sl, IntPtr.Zero));
                    foreach (FWPM_FILTER0 f0 in m.Filters) { FWPM_FILTER0 f = f0; ulong id; Check("FwpmFilterAdd0", Native.FwpmFilterAdd0(handle, ref f, IntPtr.Zero, out id)); ids.Add(id); }
                    Check("FwpmTransactionCommit0", Native.FwpmTransactionCommit0(handle)); inTxn = false;
                }
            }
            catch { if (inTxn) { lock (gate) { if (handle != IntPtr.Zero) Native.FwpmTransactionAbort0(handle); } } throw; }
            finally { m.Free(); }
            return ids.ToArray();
        }
        static bool Exists(string what, uint rc, IntPtr obj, uint notFound)
        {
            if (rc == 0) { Native.FwpmFreeMemory0(ref obj); return true; }
            if (rc == notFound) return false;
            throw new InvalidOperationException(what + " lookup failed 0x" + rc.ToString("X8"));
        }
        public bool SubLayerExists() { Guid k = Plan.SubLayerKey; IntPtr o; lock (gate) { return Exists("SubLayer", Native.FwpmSubLayerGetByKey0(handle, ref k, out o), o, 0x80320007); } }
        public bool ProviderExists() { Guid k = Plan.ProviderKey; IntPtr o; lock (gate) { return Exists("Provider", Native.FwpmProviderGetByKey0(handle, ref k, out o), o, 0x80320005); } }
        public bool FilterExists(Guid key) { IntPtr o; lock (gate) { return Exists("Filter", Native.FwpmFilterGetByKey0(handle, ref key, out o), o, 0x80320003); } }
    }
}
'@

function Initialize-FenceType {
    if (-not ('BlarAI.Wfp1740.Plan' -as [type])) { Add-Type -TypeDefinition $csharp -Language CSharp }
}

function Get-OperatorTokenSids {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{ User = $id.User.Value; Groups = @($id.Groups | ForEach-Object { $_.Value }) }
}

function Test-DiscriminateSafe {
    # PURE. The separation test names the operator on purpose, so it is allowed only as the explicit mode,
    # only for the CURRENT operator SID, only with a synthetic restricting SID, and only app-scoped to a
    # program file under the throwaway fixture root.
    param([string]$OperatorSid, [string]$CurrentUserSid, [string]$SyntheticSid, [string]$AppPath, [bool]$Allowed)
    $e = [System.Collections.ArrayList]::new()
    if (-not $Allowed) { [void]$e.Add('discriminate needs -AllowOperatorSid') }
    if ($OperatorSid -ne $CurrentUserSid) { [void]$e.Add('operator SID is not the current user') }
    if ($SyntheticSid -notmatch '^S-1-5-80(-\d+){5}$') { [void]$e.Add("synthetic SID must be an S-1-5-80 SID: '$SyntheticSid'") }
    if (-not [BlarAI.Wfp1740.Plan]::IsAcceptableAppPath($AppPath)) { [void]$e.Add("app path not acceptable: '$AppPath'") }
    return @($e)
}

function Test-TargetSafe {
    # PURE. The fence must never be able to match the operator's own identity.
    param([string]$Kind, [string]$Sid, [string]$OperatorSid, [string[]]$OperatorGroups = @())
    $e = [System.Collections.ArrayList]::new()
    if (-not [BlarAI.Wfp1740.Plan]::IsAcceptable($Kind, $Sid)) { [void]$e.Add("not an acceptable $Kind SID: '$Sid'") }
    if ($Sid -eq $OperatorSid) { [void]$e.Add('target is the OPERATOR SID') }
    if ($OperatorGroups -contains $Sid) { [void]$e.Add('target is a group in the operator token') }
    return @($e)
}

function Test-TcpConnect([string]$Address, [int]$Port = 443, [int]$TimeoutMs = 2000) {
    $c = [Net.Sockets.TcpClient]::new()
    try { $iar = $c.BeginConnect($Address, $Port, $null, $null); if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { $c.EndConnect($iar); return $true }; return $false }
    catch { return $false } finally { $c.Close() }
}

function Get-FenceState {
    $e = [BlarAI.Wfp1740.Engine]::Open($false, 'BlarAI #1740 fence read-only check')
    try {
        $keys = @([BlarAI.Wfp1740.Plan]::Build('user', 'S-1-5-21-1-2-3-1001').Filters | ForEach-Object { $_.Key })
        $keys += @('f1740005-0000-4d8e-9a31-2b6d4c8e1f31', 'f1740006-0000-4d8e-9a31-2b6d4c8e1f32' | ForEach-Object { [guid]$_ })   # discriminate-only permits
        [ordered]@{ sublayer = $e.SubLayerExists(); provider = $e.ProviderExists()
                    filters = @($keys | Where-Object { $e.FilterExists($_) } | ForEach-Object { [string]$_ }) }
    } finally { $e.Close() }
}

function Invoke-SelfTest {
    Initialize-FenceType
    $script:fail = 0
    function Check([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" } else { Write-Host "  [FAIL] $n"; $script:fail++ } }
    $u = 'S-1-5-21-1111111111-2222222222-3333333333-1009'
    $s80 = 'S-1-5-80-1-2-3-4-5'
    $pkg = 'S-1-15-2-1-2-3-4-5-6-7'
    Check 'user SID accepted' ([BlarAI.Wfp1740.Plan]::IsAcceptable('user', $u))
    Check 'synthetic S-1-5-80 accepted as user kind' ([BlarAI.Wfp1740.Plan]::IsAcceptable('user', $s80))
    Check 'package SID accepted as package kind' ([BlarAI.Wfp1740.Plan]::IsAcceptable('package', $pkg))
    foreach ($bad in 'S-1-1-0', 'S-1-5-11', 'S-1-5-32-545', 'S-1-5-18', 'S-1-15-2-1', '', 'x') {
        Check "user kind refuses '$bad'" (-not [BlarAI.Wfp1740.Plan]::IsAcceptable('user', $bad))
        Check "package kind refuses '$bad'" (-not [BlarAI.Wfp1740.Plan]::IsAcceptable('package', $bad))
    }
    Check 'package kind refuses a user SID' (-not [BlarAI.Wfp1740.Plan]::IsAcceptable('package', $u))
    $p = [BlarAI.Wfp1740.Plan]::Build('user', $u)
    Check "user SD is exactly D:(A;;CC;;;$u)" ($p.Describe -eq "ALE_USER_ID SD D:(A;;CC;;;$u)")
    $q = [BlarAI.Wfp1740.Plan]::Build('package', $pkg)
    Check 'package value is the binary SID' ((New-Object Security.Principal.SecurityIdentifier($q.Value, 0)).Value -eq $pkg)
    Check 'four filters, permits outrank blocks' (($p.Filters.Count -eq 4) -and (($p.Filters | Where-Object Action -eq 0x1002)[0].Weight -gt ($p.Filters | Where-Object Action -eq 0x1001)[0].Weight))
    Check 'operator SID refused by Test-TargetSafe' ((Test-TargetSafe 'user' $u $u @()).Count -ge 1)
    Check 'operator group refused by Test-TargetSafe' ((Test-TargetSafe 'user' $s80 'S-1-5-21-9-9-9-1001' @($s80)).Count -ge 1)
    $Mar = [Runtime.InteropServices.Marshal]
    Check 'x64 sizeof FWPM_FILTER0 == 200' ($Mar::SizeOf([type][BlarAI.Wfp1740.FWPM_FILTER0]) -eq 200)
    Check 'x64 sizeof FWPM_FILTER_CONDITION0 == 40' ($Mar::SizeOf([type][BlarAI.Wfp1740.FWPM_FILTER_CONDITION0]) -eq 40)
    foreach ($kind in 'user', 'package') {
        $plan = [BlarAI.Wfp1740.Plan]::Build($kind, $(if ($kind -eq 'user') { $u } else { $pkg }))
        $m = [BlarAI.Wfp1740.Marshalled]::Build($plan)
        try {
            $ok = $true; $cs = $Mar::SizeOf([type][BlarAI.Wfp1740.FWPM_FILTER_CONDITION0])
            foreach ($f in $m.Filters) {
                $has = $false
                for ($j = 0; $j -lt $f.numFilterConditions; $j++) {
                    $c = $Mar::PtrToStructure([IntPtr]($f.filterCondition.ToInt64() + $j * $cs), [type][BlarAI.Wfp1740.FWPM_FILTER_CONDITION0])
                    $want = if ($kind -eq 'user') { [BlarAI.Wfp1740.Plan]::CondAleUserId } else { [BlarAI.Wfp1740.Plan]::CondAlePackageId }
                    if ($c.fieldKey -eq $want) { $has = $true }
                }
                if (-not $has) { $ok = $false }
            }
            Check "every $kind filter carries the identity condition" $ok
        } finally { $m.Free() }
    }
    # ---- discriminate mode
    $op = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
    $syn = 'S-1-5-80-1-2-3-4-5'
    $app = "$env:SystemRoot\System32\cmd.exe"
    $fixDir = 'C:\blarai-spike-1740\selftest-fence'
    $fixApp = Join-Path $fixDir 'prog.exe'
    $madeRoot = -not (Test-Path 'C:\blarai-spike-1740')
    New-Item -ItemType Directory -Force $fixDir | Out-Null
    Copy-Item $app $fixApp -Force
    try {
        $dp = [BlarAI.Wfp1740.Plan]::BuildDiscriminate($op, $syn, $fixApp, $true)
        $db = [BlarAI.Wfp1740.Plan]::BuildDiscriminate($op, $syn, $fixApp, $false)
        Check 'discriminate with permit has 6 filters, block-only has 4' (($dp.Filters.Count -eq 6) -and ($db.Filters.Count -eq 4))
        Check 'discriminate block SD names exactly the operator and the synthetic SID' ($dp.Describe -match [regex]::Escape("(A;;CC;;;$op)(A;;CC;;;$syn)"))
        Check 'discriminate permit SD names the operator alone' ($dp.Describe -match [regex]::Escape("permit SD D:(A;;CC;;;$op)"))
        Check 'discriminate permit outranks block' ((($dp.Filters | Where-Object { $_.Action -eq 0x1002 -and $_.IdentityKind -eq 'user' })[0].Weight) -gt (($dp.Filters | Where-Object Action -eq 0x1001)[0].Weight))
        Check 'every discriminate filter is app-scoped' (@($dp.Filters | Where-Object { $null -eq $_.AppPath }).Count -eq 0)
        foreach ($bad in @('', "$env:SystemRoot\System32\cmd.exe", 'C:\blarai-spike-1740\nope.exe', 'C:\blarai-spike-1740\..\Windows\System32\cmd.exe')) {
            $threw = $false; try { [void][BlarAI.Wfp1740.Plan]::BuildDiscriminate($op, $syn, $bad, $true) } catch { $threw = $true }
            Check "discriminate refuses app path '$bad'" $threw
        }
        $threw = $false; try { [void][BlarAI.Wfp1740.Plan]::BuildDiscriminate($op, $op, $fixApp, $true) } catch { $threw = $true }
        Check 'discriminate refuses synthetic SID equal to the operator' $threw
        $threw = $false; try { [void][BlarAI.Wfp1740.Plan]::BuildDiscriminate('S-1-1-0', $syn, $fixApp, $true) } catch { $threw = $true }
        Check 'discriminate refuses a non-account operator SID' $threw
        Check 'Test-DiscriminateSafe accepts the intended call' ((Test-DiscriminateSafe $op $op $syn $fixApp $true).Count -eq 0)
        Check 'Test-DiscriminateSafe refuses without -AllowOperatorSid' ((Test-DiscriminateSafe $op $op $syn $fixApp $false).Count -ge 1)
        Check 'Test-DiscriminateSafe refuses an operator SID that is not the current user' ((Test-DiscriminateSafe $op 'S-1-5-21-9-9-9-1001' $syn $fixApp $true).Count -ge 1)
        Check 'Test-DiscriminateSafe refuses a real-account synthetic SID' ((Test-DiscriminateSafe $op $op 'S-1-5-21-5-5-5-1009' $fixApp $true).Count -ge 1)
        $m = [BlarAI.Wfp1740.Marshalled]::Build($dp)
        try {
            $cs = $Mar::SizeOf([type][BlarAI.Wfp1740.FWPM_FILTER_CONDITION0]); $allApp = $true
            foreach ($f in $m.Filters) {
                $hasApp = $false
                for ($j = 0; $j -lt $f.numFilterConditions; $j++) {
                    $c = $Mar::PtrToStructure([IntPtr]($f.filterCondition.ToInt64() + $j * $cs), [type][BlarAI.Wfp1740.FWPM_FILTER_CONDITION0])
                    if ($c.fieldKey -eq [BlarAI.Wfp1740.Plan]::CondAleAppId -and $c.conditionValue.type -eq 12) { $hasApp = $true }
                }
                if (-not $hasApp) { $allApp = $false }
            }
            Check 'every marshalled discriminate filter carries ALE_APP_ID / BYTE_BLOB' $allApp
        } finally { $m.Free() }
    } finally {
        Remove-Item $fixDir -Recurse -Force -ErrorAction SilentlyContinue
        if ($madeRoot) { Remove-Item 'C:\blarai-spike-1740' -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "SelfTest failures: $script:fail"
    return $(if ($script:fail) { 1 } else { 0 })
}

function Invoke-Hold {
    $report = [ordered]@{ fence = '#1740'; kind = $Kind; target = $TargetSid; started = (Get-Date).ToString('o'); watchdog = @() }
    $code = 4; $engine = $null
    New-Item -ItemType Directory -Force $MarkerDir | Out-Null
    foreach ($f in 'ARMED', 'DONE') { Remove-Item (Join-Path $MarkerDir $f) -ErrorAction SilentlyContinue }
    try {
        Initialize-FenceType
        $op = Get-OperatorTokenSids
        if ($Kind -eq 'discriminate') {
            $bad = Test-DiscriminateSafe $op.User $op.User $SyntheticSid $AppPath $AllowOperatorSid.IsPresent
        } else {
            $bad = Test-TargetSafe $Kind $TargetSid $op.User $op.Groups
        }
        if ($bad.Count) { $report.error = ($bad -join '; '); $code = 2; return }
        $pre = Get-FenceState
        if ($pre.sublayer -or $pre.provider -or $pre.filters.Count) { $report.error = 'stale fence objects present'; $code = 2; return }
        if (-not (Test-TcpConnect '1.1.1.1')) { $report.error = 'operator has no baseline egress'; $code = 2; return }
        $plan = if ($Kind -eq 'discriminate') { [BlarAI.Wfp1740.Plan]::BuildDiscriminate($op.User, $SyntheticSid, $AppPath, ($Variant -eq 'block-permit')) } else { [BlarAI.Wfp1740.Plan]::Build($Kind, $TargetSid) }
        $report.condition = $plan.Describe; $report.variant = $Variant
        $engine = [BlarAI.Wfp1740.Engine]::Open($true, 'BlarAI #1740 fence (dynamic)')
        $engine.ArmDeadMan($HoldSeconds + 30)
        $report.filter_ids = @($engine.AddAll($plan))
        $report.armed = (Get-Date).ToString('o')
        Set-Content (Join-Path $MarkerDir 'ARMED') $report.armed
        $deadline = (Get-Date).AddSeconds($HoldSeconds); $consec = 0; $code = 0
        while ((Get-Date) -lt $deadline -and -not (Test-Path (Join-Path $MarkerDir 'DONE'))) {
            $ok = Test-TcpConnect '1.1.1.1'
            $report.watchdog += [ordered]@{ t = (Get-Date).ToString('o'); ok = $ok }
            if ($ok) { $consec = 0 } else { $consec++ }
            if ($consec -ge 2) { $engine.Close(); $code = 3; $report.error = 'operator traffic affected'; break }
            Start-Sleep -Milliseconds 2000
        }
    } catch {
        $report.error = $_.Exception.Message; $code = 4
    } finally {
        if ($engine) { $engine.Close(); $report.close_status = ('0x{0:X8}' -f $engine.LastCloseStatus) }
        try {
            $post = Get-FenceState; $report.after = $post
            if ($post.sublayer -or $post.provider -or $post.filters.Count) { $code = 7 }
        } catch { $report.after = "error: $($_.Exception.Message)"; $code = 7 }
        $report.finished = (Get-Date).ToString('o'); $report.exit_code = $code
        ($report | ConvertTo-Json -Depth 6) | Set-Content (Join-Path $MarkerDir 'fence.json') -Encoding UTF8
        Remove-Item (Join-Path $MarkerDir 'ARMED') -ErrorAction SilentlyContinue
    }
    return $code
}

$modes = @($SelfTest, $DryRun, $Hold) | Where-Object { $_ }
if (@($modes).Count -ne 1) { Write-Host 'choose exactly one of -SelfTest, -DryRun, -Hold'; exit 2 }
if ($HoldSeconds -lt 5 -or $HoldSeconds -gt 600) { Write-Host 'HoldSeconds must be 5..600'; exit 2 }
if ($SelfTest) { exit (Invoke-SelfTest) }
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $elevated) { Write-Host 'requires an elevated shell'; exit 2 }
if ($DryRun) {
    Initialize-FenceType
    if ($Kind -eq 'discriminate') {
        $op = Get-OperatorTokenSids
        $bad = Test-DiscriminateSafe $op.User $op.User $SyntheticSid $AppPath $AllowOperatorSid.IsPresent
        Write-Host ($(if ($bad.Count) { 'REFUSED: ' + ($bad -join '; ') } else { 'target OK: ' + [BlarAI.Wfp1740.Plan]::BuildDiscriminate($op.User, $SyntheticSid, $AppPath, ($Variant -eq 'block-permit')).Describe }))
    } elseif ($TargetSid) { $op = Get-OperatorTokenSids; $bad = Test-TargetSafe $Kind $TargetSid $op.User $op.Groups; Write-Host ($(if ($bad.Count) { 'REFUSED: ' + ($bad -join '; ') } else { 'target OK: ' + [BlarAI.Wfp1740.Plan]::Build($Kind, $TargetSid).Describe })) }
    (Get-FenceState) | ConvertTo-Json | Write-Host
    Write-Host 'DRY RUN: nothing added.'
    exit 0
}
if ($Hold) { exit (Invoke-Hold) }
