//! halfset: a guarded Windows Filtering Platform (WFP) harness built as a cargo
//! example inside the pinned srt-win source tree.
//!
//! Contract
//! - Every subcommand prints exactly one JSON object on stdout and exits with
//!   the code table below.
//! - Only three sublayers (S1, S2, S3) can be added to, deleted from or
//!   enumerated. The sublayer, SID and arming guards are deny-by-default and
//!   evaluated before the first engine open of the process. The empty-sublayer
//!   guard and the stop sweep need the engine: they run after a read-only
//!   enumeration opens it and before the first mutating call. Every error path
//!   denies.
//! - `install`, `delete-filter`, `delete-sublayer` and `uninstall` are armed by
//!   `--live <proof.json>`: the proof must name this exe's own sha256 and the
//!   build-embedded `halfset.rs` sha256, report zero failed checks and be at
//!   most 24 hours old. Without it they exit 12 before any engine open.
//! - Every call that reaches the WFP engine goes through `trace_engine_open`,
//!   which appends one line to the file named by `HALFSET_ENGINE_OPEN_TRACE`
//!   (when set) before the engine is touched, and counts the call in-process.
//! - `selftest-refusals` exercises every guard against fake environments and a
//!   fake filter source; it opens no engine and asserts that count is zero.
//! - A build made with `RUSTFLAGS="--cfg halfset_toggle"` exists only for the
//!   guard toggle tests. It can switch a guard off by environment variable and
//!   can never open the engine: every engine entry point refuses in that build.
//!   The shipped build contains neither the toggle code nor its variable name.
//!
//! Exit codes: 0 ok, 1 selftest failed, 2 usage, 3 sublayer refused, 4 SID
//! refused, 5 sublayer not empty, 6 not elevated and engine unreadable,
//! 7 engine denied (mutating call, or elevated), 8 read-back mismatch,
//! 9 stop (a filter of ours or srt-win's outside S1/S2/S3),
//! 10 engine error (not an access denial), 11 delete target not under the
//! sublayer, 12 not armed, 13 trace file unusable (engine not touched).

#![allow(unexpected_cfgs)]

use serde_json::{Value, json};
use srt_win::sid::SidExistence;
use srt_win::wfp::{WfpAccessDenied, parse_guid, parse_port_range};
use std::ffi::c_void;
use std::io::Write;
use std::sync::atomic::{AtomicUsize, Ordering};
use windows::Win32::Foundation::{CloseHandle, HANDLE};
use windows::Win32::NetworkManagement::WindowsFilteringPlatform::{
    FWP_ACTION_BLOCK, FWP_ACTION_PERMIT, FWP_FILTER_ENUM_OVERLAPPING, FWP_UINT64,
    FWPM_CONDITION_ALE_USER_ID, FWPM_FILTER_ENUM_TEMPLATE0, FWPM_FILTER0,
    FWPM_LAYER_ALE_AUTH_CONNECT_V4, FWPM_LAYER_ALE_AUTH_CONNECT_V6, FWPM_SUBLAYER0,
    FwpmEngineClose0, FwpmEngineOpen0, FwpmFilterCreateEnumHandle0, FwpmFilterDeleteByKey0,
    FwpmFilterDestroyEnumHandle0, FwpmFilterEnum0, FwpmFreeMemory0, FwpmSubLayerDeleteByKey0,
    FwpmSubLayerGetByKey0,
};
use windows::Win32::Security::{
    GetTokenInformation, TOKEN_ELEVATION, TOKEN_GROUPS, TOKEN_QUERY, TokenElevation, TokenGroups,
};
use windows::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};
use windows::core::{GUID, PCWSTR};

// ───────────────────────────── fixed constants ─────────────────────────────

const VERSION: &str = "halfset 1.0.0";
const PINNED_SRT_WIN_SHA: &str = "24eb39e94a6de386e83d126c52317d8e0fa49522";
const PINNED_LOCK_SHA256: Option<&str> = option_env!("HALFSET_PINNED_LOCK_SHA256");
const EMBEDDED_RS_SHA256: Option<&str> = option_env!("HALFSET_RS_SHA256");
const PROOF_SCHEMA: &str = "nep5-1763-proof-v1";
const PROOF_MAX_AGE_SECS: i64 = 24 * 3600;
const PROOF_MAX_FUTURE_SECS: i64 = 300;
const PROOF_MAX_BYTES: u64 = 1 << 20;

const S1: GUID = GUID::from_u128(0xc971a69f_d6ab_4885_9b49_506d8aa51c86);
const S2: GUID = GUID::from_u128(0x3e29ae7e_fd9f_413a_8b8d_da9bd3a96359);
const S3: GUID = GUID::from_u128(0x6cf901ba_a6cd_4846_81a5_2598c55bdef5);
const SRT_DEFAULT_SUBLAYER: GUID = GUID::from_u128(0x2c5d0ad6_5f3b_4d4e_9b8f_1a3e7c9d0b21);
const OLD_ARM3_SUBLAYER: GUID = GUID::from_u128(0x7e1f6a10_5c0b_4d8e_9a31_2b6d4c8e3f02);

const ALLOWED_SUBLAYERS: [(GUID, &str); 3] = [(S1, "S1"), (S2, "S2"), (S3, "S3")];
/// Sublayers whose filters make a sweep stop even if a name does not match.
const FORBIDDEN_SUBLAYERS: [GUID; 2] = [SRT_DEFAULT_SUBLAYER, OLD_ARM3_SUBLAYER];

const SPIKE_NAME: &str = "blarai-spike";
const SPIKE_SID: &str = "S-1-5-21-1000000001-1000000002-1000000003-1271";
const STALE_SID: &str = "S-1-5-21-17630000-17630001-17630002-91763";
const NAME_MARKERS: [&str; 2] = ["srt-win", "BlarAI #1763"];

const FWP_E_FILTER_NOT_FOUND: u32 = 0x8032_0003;
const FWP_E_SUBLAYER_NOT_FOUND: u32 = 0x8032_0007;
const FWP_E_IN_USE: u32 = 0x8032_000A;
const FWP_E_ACCESS_DENIED: u32 = 0x8032_0028;
const ERROR_ACCESS_DENIED: u32 = 5;

// ───────────────────────────── toggle (test builds only) ─────────────────────

#[cfg(halfset_toggle)]
fn toggled_off(guard: &str) -> bool {
    std::env::var("HALFSET_TOGGLE_OFF")
        .map(|v| v.split(',').any(|g| g.trim() == guard))
        .unwrap_or(false)
}
#[cfg(not(halfset_toggle))]
#[inline(always)]
fn toggled_off(_guard: &str) -> bool {
    false
}

// ───────────────────────────── errors and refusals ────────────────────────────

#[derive(Debug, Clone)]
struct Refusal {
    exit: i32,
    guard: &'static str,
    detail: String,
}

fn refuse(exit: i32, guard: &'static str, detail: impl Into<String>) -> Refusal {
    Refusal {
        exit,
        guard,
        detail: detail.into(),
    }
}

#[derive(Debug, Clone)]
struct EngErr {
    call: String,
    rc: u32,
}

impl EngErr {
    fn new(call: &str, rc: u32) -> Self {
        Self {
            call: call.to_string(),
            rc,
        }
    }
    fn denied(&self) -> bool {
        self.rc == ERROR_ACCESS_DENIED || self.rc == FWP_E_ACCESS_DENIED
    }
    fn from_anyhow(e: &anyhow::Error) -> Self {
        if let Some(d) = e.downcast_ref::<WfpAccessDenied>() {
            return Self::new(d.call, d.rc);
        }
        let msg = format!("{e:#}");
        let rc = msg
            .find("0x")
            .and_then(|i| msg.get(i + 2..i + 10))
            .and_then(|h| u32::from_str_radix(h, 16).ok())
            .unwrap_or(0);
        Self {
            call: msg,
            rc,
        }
    }
}

/// Maps an engine error to (exit code, label). `write` is true for mutating
/// subcommands.
fn classify(elevated: bool, e: &EngErr, write: bool) -> (i32, &'static str) {
    if e.call == "trace_open_failed" || e.call == "trace_write_failed" {
        return (13, "trace_failed");
    }
    if !e.denied() {
        return (10, "engine_error");
    }
    if write || elevated {
        return (7, "engine_denied");
    }
    (6, "not_elevated")
}

// ───────────────────────────── engine-open trace ──────────────────────────────

static ENGINE_OPENS: AtomicUsize = AtomicUsize::new(0);

/// Records one engine touch. Returns Err (and the caller must not touch the
/// engine) when the trace file is configured but cannot be appended to.
fn trace_engine_open(ctx: &str) -> Result<(), EngErr> {
    ENGINE_OPENS.fetch_add(1, Ordering::SeqCst);
    if let Ok(path) = std::env::var("HALFSET_ENGINE_OPEN_TRACE") {
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .map_err(|_| EngErr::new("trace_open_failed", 0))?;
        writeln!(f, "engine_open {ctx}").map_err(|_| EngErr::new("trace_write_failed", 0))?;
    }
    Ok(())
}

// ───────────────────────────── sha256 and the arming proof ───────────────────

const K256: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

/// SHA-256 of `data` as lowercase hex (FIPS 180-4).
fn sha256_hex(data: &[u8]) -> String {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for chunk in msg.chunks_exact(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[4 * i],
                chunk[4 * i + 1],
                chunk[4 * i + 2],
                chunk[4 * i + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7]
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K256[i])
                .wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v = [
                t1.wrapping_add(t2),
                v[0],
                v[1],
                v[2],
                v[3].wrapping_add(t1),
                v[4],
                v[5],
                v[6],
            ];
        }
        for i in 0..8 {
            h[i] = h[i].wrapping_add(v[i]);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}

fn is_sha256_hex(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit())
}

/// Days since 1970-01-01 for a proleptic Gregorian date.
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

/// Parses `YYYY-MM-DDTHH:MM:SS[.fraction](Z|+HH:MM|-HH:MM)` to unix seconds.
/// A timestamp without a zone designator is rejected.
fn parse_utc(s: &str) -> Option<i64> {
    let b = s.as_bytes();
    if b.len() < 20 || !s.is_ascii() {
        return None;
    }
    let num = |a: usize, z: usize| -> Option<i64> {
        let t = &s[a..z];
        if t.bytes().all(|c| c.is_ascii_digit()) {
            t.parse().ok()
        } else {
            None
        }
    };
    if b[4] != b'-'
        || b[7] != b'-'
        || (b[10] != b'T' && b[10] != b't')
        || b[13] != b':'
        || b[16] != b':'
    {
        return None;
    }
    let (y, mo, d, h, mi, se) = (
        num(0, 4)?,
        num(5, 7)?,
        num(8, 10)?,
        num(11, 13)?,
        num(14, 16)?,
        num(17, 19)?,
    );
    if !(1..=12).contains(&mo) || !(1..=31).contains(&d) || h > 23 || mi > 59 || se > 60 {
        return None;
    }
    let mut i = 19;
    if b[i] == b'.' {
        i += 1;
        let st = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == st {
            return None;
        }
    }
    let off = match b.get(i)? {
        b'Z' | b'z' if i + 1 == b.len() => 0,
        b'+' | b'-' if i + 6 == b.len() && b[i + 3] == b':' => {
            let oh = num(i + 1, i + 3)?;
            let om = num(i + 4, i + 6)?;
            if oh > 23 || om > 59 {
                return None;
            }
            let v = oh * 3600 + om * 60;
            if b[i] == b'+' { v } else { -v }
        }
        _ => return None,
    };
    Some(days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + se - off)
}

/// Validates the arming proof text: the schema, this exe's own sha256, the
/// build-embedded halfset.rs sha256, zero failed checks and a `written_utc`
/// no older than 24 hours.
fn check_proof(
    text: &str,
    own_exe_sha: &str,
    embedded_rs: Option<&str>,
    now: i64,
) -> Result<(), String> {
    let v: Value = serde_json::from_str(text).map_err(|e| format!("proof is not JSON: {e}"))?;
    if v.get("schema").and_then(|x| x.as_str()) != Some(PROOF_SCHEMA) {
        return Err(format!("proof schema is not {PROOF_SCHEMA}"));
    }
    let want_rs = embedded_rs.ok_or("this build embeds no halfset.rs sha256")?;
    if !is_sha256_hex(want_rs) || !is_sha256_hex(own_exe_sha) {
        return Err("own or embedded sha256 is malformed".into());
    }
    let got_exe = v
        .get("halfset_exe_sha256")
        .and_then(|x| x.as_str())
        .unwrap_or("");
    if !got_exe.eq_ignore_ascii_case(own_exe_sha) {
        return Err("proof halfset_exe_sha256 is not this exe".into());
    }
    let got_rs = v
        .get("halfset_rs_sha256")
        .and_then(|x| x.as_str())
        .unwrap_or("");
    if !got_rs.eq_ignore_ascii_case(want_rs) {
        return Err("proof halfset_rs_sha256 is not this build's source".into());
    }
    if v.get("checks_failed").and_then(|x| x.as_u64()) != Some(0) {
        return Err("proof checks_failed is not 0".into());
    }
    let ts = v
        .get("written_utc")
        .and_then(|x| x.as_str())
        .and_then(parse_utc)
        .ok_or("proof written_utc is missing or malformed")?;
    if ts > now + PROOF_MAX_FUTURE_SECS {
        return Err("proof written_utc is in the future".into());
    }
    if now - ts > PROOF_MAX_AGE_SECS {
        return Err("proof is older than 24 hours".into());
    }
    Ok(())
}

fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn own_exe_sha256() -> Result<String, String> {
    let p = std::env::current_exe().map_err(|e| format!("current_exe: {e}"))?;
    let bytes = std::fs::read(&p).map_err(|e| format!("read own exe: {e}"))?;
    Ok(sha256_hex(&bytes))
}

/// Arming interlock for the mutating subcommands (exit 12). Runs before any
/// engine open.
fn guard_armed(
    live: Option<&str>,
    own_sha: &dyn Fn() -> Result<String, String>,
    now: i64,
) -> Result<(), Refusal> {
    if toggled_off("interlock") {
        return Ok(());
    }
    let path = live.ok_or_else(|| refuse(12, "not_armed", "--live <proof.json> is required"))?;
    let meta = std::fs::metadata(path)
        .map_err(|e| refuse(12, "not_armed", format!("cannot read proof: {e}")))?;
    if !meta.is_file() || meta.len() > PROOF_MAX_BYTES {
        return Err(refuse(
            12,
            "not_armed",
            "proof is not a regular file within the size cap",
        ));
    }
    let text = std::fs::read_to_string(path)
        .map_err(|e| refuse(12, "not_armed", format!("cannot read proof: {e}")))?;
    let sha = own_sha().map_err(|e| refuse(12, "not_armed", e))?;
    check_proof(&text, &sha, EMBEDDED_RS_SHA256, now).map_err(|e| refuse(12, "not_armed", e))
}

// ───────────────────────────── helpers ────────────────────────────────────────

fn guid_str(g: &GUID) -> String {
    format!(
        "{:08x}-{:04x}-{:04x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
        g.data1,
        g.data2,
        g.data3,
        g.data4[0],
        g.data4[1],
        g.data4[2],
        g.data4[3],
        g.data4[4],
        g.data4[5],
        g.data4[6],
        g.data4[7]
    )
}

fn layer_name(g: &GUID) -> String {
    if *g == FWPM_LAYER_ALE_AUTH_CONNECT_V4 {
        "ale_auth_connect_v4".into()
    } else if *g == FWPM_LAYER_ALE_AUTH_CONNECT_V6 {
        "ale_auth_connect_v6".into()
    } else {
        guid_str(g)
    }
}

fn sublayer_label(g: &GUID) -> Option<&'static str> {
    ALLOWED_SUBLAYERS
        .iter()
        .find(|(a, _)| a == g)
        .map(|(_, l)| *l)
}

fn is_elevated() -> Option<bool> {
    unsafe {
        let mut tok = HANDLE::default();
        OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut tok).ok()?;
        let mut el = TOKEN_ELEVATION::default();
        let mut len = 0u32;
        let r = GetTokenInformation(
            tok,
            TokenElevation,
            Some(&mut el as *mut _ as *mut c_void),
            std::mem::size_of::<TOKEN_ELEVATION>() as u32,
            &mut len,
        );
        let _ = CloseHandle(tok);
        r.ok()?;
        Some(el.TokenIsElevated != 0)
    }
}

fn token_group_sids() -> Result<Vec<String>, String> {
    unsafe {
        let mut tok = HANDLE::default();
        OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut tok)
            .map_err(|e| format!("OpenProcessToken: {e}"))?;
        let mut len = 0u32;
        let _ = GetTokenInformation(tok, TokenGroups, None, 0, &mut len);
        if len == 0 {
            let _ = CloseHandle(tok);
            return Err("GetTokenInformation(TokenGroups) sizing returned 0".into());
        }
        // u64 backing keeps the buffer aligned for TOKEN_GROUPS.
        let mut buf = vec![0u64; (len as usize).div_ceil(8)];
        let r = GetTokenInformation(
            tok,
            TokenGroups,
            Some(buf.as_mut_ptr() as *mut c_void),
            len,
            &mut len,
        );
        let _ = CloseHandle(tok);
        r.map_err(|e| format!("GetTokenInformation(TokenGroups): {e}"))?;
        let tg = &*(buf.as_ptr() as *const TOKEN_GROUPS);
        let first = tg.Groups.as_ptr();
        let mut out = Vec::with_capacity(tg.GroupCount as usize);
        for i in 0..tg.GroupCount as usize {
            let sa = &*first.add(i);
            out.push(
                srt_win::sid::psid_to_string(sa.Sid).map_err(|e| format!("group sid: {e:#}"))?,
            );
        }
        Ok(out)
    }
}

// ───────────────────────────── SID environment ────────────────────────────────

trait SidEnv {
    fn operator_sid(&self) -> Result<String, String>;
    fn token_group_sids(&self) -> Result<Vec<String>, String>;
    fn lookup_account(&self, name: &str) -> Result<String, String>;
    fn existence(&self, sid: &str) -> Result<SidExistence, String>;
}

struct RealSidEnv;
impl SidEnv for RealSidEnv {
    fn operator_sid(&self) -> Result<String, String> {
        srt_win::sid::current_user_sid().map_err(|e| format!("{e:#}"))
    }
    fn token_group_sids(&self) -> Result<Vec<String>, String> {
        token_group_sids()
    }
    fn lookup_account(&self, name: &str) -> Result<String, String> {
        srt_win::sid::lookup_account_sid(name).map_err(|e| format!("{e:#}"))
    }
    fn existence(&self, sid: &str) -> Result<SidExistence, String> {
        srt_win::sid::sid_account_exists(sid).map_err(|e| format!("{e:#}"))
    }
}

// ───────────────────────────── guards 1 and 2 ─────────────────────────────────

/// Guard 1: only S1, S2, S3.
fn guard_sublayer(s: &GUID) -> Result<(), Refusal> {
    if toggled_off("sublayer") {
        return Ok(());
    }
    if sublayer_label(s).is_some() {
        return Ok(());
    }
    let why = if *s == SRT_DEFAULT_SUBLAYER {
        "srt-win default sublayer"
    } else if *s == OLD_ARM3_SUBLAYER {
        "old arm 3 sublayer"
    } else {
        "not in the allowlist"
    };
    Err(refuse(
        3,
        "sublayer_allowlist",
        format!("{} refused: {why}", guid_str(s)),
    ))
}

fn well_known_prefix(sid: &str) -> bool {
    let u = sid.to_ascii_uppercase();
    u.starts_with("S-1-5-32-")
        || u.starts_with("S-1-1-")
        || u.starts_with("S-1-2-")
        || u.starts_with("S-1-3-")
        || u.starts_with("S-1-5-80-")
        || u.starts_with("S-1-16-")
        || matches!(
            u.as_str(),
            "S-1-5-18" | "S-1-5-19" | "S-1-5-20" | "S-1-5-11" | "S-1-5-4" | "S-1-5-2" | "S-1-5-7"
        )
}

/// Guard 2: `install` SID allowlist. Exact string match against the two
/// recorded test SIDs only; then the SID must not be the caller's user or any
/// caller token group; then blarai-spike's SID must equal the live
/// LookupAccountName result and the stale SID must be unmapped.
fn guard_install_sid(sid: &str, env: &dyn SidEnv) -> Result<(), Refusal> {
    if toggled_off("sid") {
        return Ok(());
    }
    let is_spike = sid == SPIKE_SID;
    let is_stale = sid == STALE_SID;
    let op = env.operator_sid();
    let groups = env.token_group_sids();
    if !is_spike && !is_stale {
        let class = if op.as_deref().map(|o| o.eq_ignore_ascii_case(sid)) == Ok(true) {
            "caller's own user SID"
        } else if groups
            .as_ref()
            .map(|g| g.iter().any(|x| x.eq_ignore_ascii_case(sid)))
            .unwrap_or(false)
        {
            "SID of a group in the caller's token"
        } else if well_known_prefix(sid) {
            "well-known SID"
        } else {
            "not in the allowlist"
        };
        return Err(refuse(4, "sid_allowlist", format!("{sid} refused: {class}")));
    }
    let op = op.map_err(|e| refuse(4, "sid_caller_token", format!("cannot read caller user: {e}")))?;
    let groups = groups
        .map_err(|e| refuse(4, "sid_caller_token", format!("cannot read caller groups: {e}")))?;
    if op.eq_ignore_ascii_case(sid) || groups.iter().any(|g| g.eq_ignore_ascii_case(sid)) {
        return Err(refuse(
            4,
            "sid_caller_token",
            format!("{sid} is the caller's user or a caller token group"),
        ));
    }
    if toggled_off("sid_lookup") {
        return Ok(());
    }
    if is_spike {
        match env.lookup_account(SPIKE_NAME) {
            Ok(s) if s == SPIKE_SID => Ok(()),
            Ok(s) => Err(refuse(
                4,
                "sid_lookup",
                format!("LookupAccountName({SPIKE_NAME}) returned {s}, not the recorded SID"),
            )),
            Err(e) => Err(refuse(
                4,
                "sid_lookup",
                format!("LookupAccountName({SPIKE_NAME}) failed: {e}"),
            )),
        }
    } else {
        match env.existence(sid) {
            Ok(SidExistence::Unmapped) => Ok(()),
            Ok(SidExistence::Mapped) => Err(refuse(4, "sid_stale", "stale SID resolves to an account")),
            Ok(SidExistence::Unknown) => {
                Err(refuse(4, "sid_stale", "stale SID lookup was inconclusive"))
            }
            Err(e) => Err(refuse(4, "sid_stale", format!("stale SID lookup failed: {e}"))),
        }
    }
}

// ───────────────────────────── filters and the filter source ─────────────────

#[derive(Debug, Clone)]
struct FilterInfo {
    key: GUID,
    layer: GUID,
    sublayer: GUID,
    name: String,
    tool: Option<String>,
    kind: Option<String>,
    user_sid: Option<String>,
    port_range: Option<[u16; 2]>,
    has_user_condition: bool,
    num_conditions: u32,
    action: u32,
    weight: Option<u64>,
}

impl FilterInfo {
    fn to_json(&self) -> Value {
        let action = if self.action == FWP_ACTION_BLOCK.0 {
            "block".to_string()
        } else if self.action == FWP_ACTION_PERMIT.0 {
            "permit".to_string()
        } else {
            format!("0x{:x}", self.action)
        };
        json!({
            "key": guid_str(&self.key),
            "layer": layer_name(&self.layer),
            "sublayer": guid_str(&self.sublayer),
            "name": self.name,
            "tool": self.tool,
            "kind": self.kind,
            "user_sid": self.user_sid,
            "port_range": self.port_range,
            "has_user_condition": self.has_user_condition,
            "num_conditions": self.num_conditions,
            "action": action,
            "weight": self.weight.map(|w| format!("0x{w:016x}")),
        })
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Scope {
    /// The two ALE connect layers only.
    Ale,
    /// Every layer.
    All,
}

trait FilterSource {
    fn filters(&self, scope: Scope) -> Result<Vec<FilterInfo>, EngErr>;
}

fn info_from(flt: &FWPM_FILTER0) -> FilterInfo {
    let name = srt_win::util::from_pwstr(flt.displayData.name);
    let mut tool = None;
    let mut kind = None;
    let mut user_sid = None;
    let mut port_range = None;
    if flt.providerData.size > 0 && !flt.providerData.data.is_null() {
        let bytes = unsafe {
            std::slice::from_raw_parts(flt.providerData.data, flt.providerData.size as usize)
        };
        if let Ok(v) = serde_json::from_slice::<Value>(bytes) {
            tool = v.get("tool").and_then(|x| x.as_str()).map(String::from);
            kind = v.get("kind").and_then(|x| x.as_str()).map(String::from);
            user_sid = v.get("user_sid").and_then(|x| x.as_str()).map(String::from);
            port_range = v.get("port_range").and_then(|x| x.as_array()).and_then(|a| {
                match (
                    a.first().and_then(|x| x.as_u64()),
                    a.get(1).and_then(|x| x.as_u64()),
                ) {
                    (Some(l), Some(h)) if l <= 65535 && h <= 65535 => Some([l as u16, h as u16]),
                    _ => None,
                }
            });
        }
    }
    let mut has_user_condition = false;
    if flt.numFilterConditions > 0 && !flt.filterCondition.is_null() {
        let conds = unsafe {
            std::slice::from_raw_parts(flt.filterCondition, flt.numFilterConditions as usize)
        };
        has_user_condition = conds
            .iter()
            .any(|c| c.fieldKey == FWPM_CONDITION_ALE_USER_ID);
    }
    let weight = if flt.weight.r#type == FWP_UINT64 {
        let p = unsafe { flt.weight.Anonymous.uint64 };
        if p.is_null() { None } else { Some(unsafe { *p }) }
    } else {
        None
    };
    FilterInfo {
        key: flt.filterKey,
        layer: flt.layerKey,
        sublayer: flt.subLayerKey,
        name,
        tool,
        kind,
        user_sid,
        port_range,
        has_user_condition,
        num_conditions: flt.numFilterConditions,
        action: flt.action.r#type.0,
        weight,
    }
}

struct Engine(HANDLE);

impl Engine {
    fn open(ctx: &str) -> Result<Self, EngErr> {
        trace_engine_open(ctx)?;
        #[cfg(halfset_toggle)]
        {
            return Err(EngErr::new("toggle_build_never_opens_engine", 0));
        }
        #[cfg(not(halfset_toggle))]
        {
            let mut h = HANDLE::default();
            let rc = unsafe { FwpmEngineOpen0(PCWSTR::null(), 0xFFFF_FFFF, None, None, &mut h) };
            if rc != 0 {
                return Err(EngErr::new("FwpmEngineOpen0", rc));
            }
            Ok(Self(h))
        }
    }

    fn enum_template(
        &self,
        tmpl: Option<&FWPM_FILTER_ENUM_TEMPLATE0>,
        label: &str,
        out: &mut Vec<FilterInfo>,
    ) -> Result<(), EngErr> {
        let mut h = HANDLE::default();
        let tp = tmpl.map(|t| t as *const FWPM_FILTER_ENUM_TEMPLATE0);
        let rc = unsafe { FwpmFilterCreateEnumHandle0(self.0, tp, &mut h) };
        if rc != 0 {
            return Err(EngErr::new(
                &format!("FwpmFilterCreateEnumHandle0({label})"),
                rc,
            ));
        }
        loop {
            let mut entries: *mut *mut FWPM_FILTER0 = std::ptr::null_mut();
            let mut n: u32 = 0;
            let rc = unsafe { FwpmFilterEnum0(self.0, h, 256, &mut entries, &mut n) };
            if rc != 0 {
                unsafe {
                    let _ = FwpmFilterDestroyEnumHandle0(self.0, h);
                }
                return Err(EngErr::new(&format!("FwpmFilterEnum0({label})"), rc));
            }
            if n == 0 {
                if !entries.is_null() {
                    unsafe { FwpmFreeMemory0(&mut (entries as *mut c_void)) };
                }
                break;
            }
            let slice = unsafe { std::slice::from_raw_parts(entries, n as usize) };
            for &fp in slice {
                if !fp.is_null() {
                    out.push(info_from(unsafe { &*fp }));
                }
            }
            unsafe { FwpmFreeMemory0(&mut (entries as *mut c_void)) };
            if (n as usize) < 256 {
                break;
            }
        }
        unsafe {
            let _ = FwpmFilterDestroyEnumHandle0(self.0, h);
        }
        Ok(())
    }

    fn delete_filter(&self, key: &GUID) -> u32 {
        unsafe { FwpmFilterDeleteByKey0(self.0, key) }
    }

    fn delete_sublayer(&self, key: &GUID) -> u32 {
        unsafe { FwpmSubLayerDeleteByKey0(self.0, key) }
    }

    /// Ok(true) if the sublayer exists, Ok(false) if the engine says not found.
    fn sublayer_exists(&self, key: &GUID) -> Result<bool, EngErr> {
        let mut p: *mut FWPM_SUBLAYER0 = std::ptr::null_mut();
        let rc = unsafe { FwpmSubLayerGetByKey0(self.0, key, &mut p) };
        if rc == 0 {
            if !p.is_null() {
                unsafe { FwpmFreeMemory0(&mut (p as *mut c_void)) };
            }
            return Ok(true);
        }
        if rc == FWP_E_SUBLAYER_NOT_FOUND {
            return Ok(false);
        }
        Err(EngErr::new("FwpmSubLayerGetByKey0", rc))
    }
}

impl FilterSource for Engine {
    fn filters(&self, scope: Scope) -> Result<Vec<FilterInfo>, EngErr> {
        let mut out = Vec::new();
        match scope {
            Scope::Ale => {
                for (layer, label) in [
                    (FWPM_LAYER_ALE_AUTH_CONNECT_V4, "ale_auth_connect_v4"),
                    (FWPM_LAYER_ALE_AUTH_CONNECT_V6, "ale_auth_connect_v6"),
                ] {
                    let mut t = FWPM_FILTER_ENUM_TEMPLATE0::default();
                    t.layerKey = layer;
                    t.enumType = FWP_FILTER_ENUM_OVERLAPPING;
                    t.actionMask = 0xFFFF_FFFF;
                    self.enum_template(Some(&t), label, &mut out)?;
                }
            }
            Scope::All => self.enum_template(None, "all_layers", &mut out)?,
        }
        Ok(out)
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        if !self.0.is_invalid() {
            unsafe {
                let _ = FwpmEngineClose0(self.0);
            }
        }
    }
}

// ───────────────────────────── guards 3 and 9 (need a filter source) ─────────

fn matches_ours(f: &FilterInfo) -> bool {
    let n = f.name.to_ascii_lowercase();
    NAME_MARKERS
        .iter()
        .any(|m| n.contains(&m.to_ascii_lowercase()))
        || f.tool.as_deref() == Some("srt-win")
        || FORBIDDEN_SUBLAYERS.contains(&f.sublayer)
}

/// Stop sweep: filters of ours or srt-win's anywhere but S1/S2/S3.
fn stop_hits(all: &[FilterInfo]) -> Vec<&FilterInfo> {
    all.iter()
        .filter(|f| sublayer_label(&f.sublayer).is_none() && matches_ours(f))
        .collect()
}

fn guard_stop_sweep(all: &[FilterInfo]) -> Result<(), Refusal> {
    if toggled_off("stop_sweep") {
        return Ok(());
    }
    let hits = stop_hits(all);
    if hits.is_empty() {
        return Ok(());
    }
    let keys: Vec<String> = hits.iter().map(|f| guid_str(&f.key)).collect();
    Err(refuse(
        9,
        "stop_sweep",
        format!(
            "{} filter(s) of ours or srt-win's outside S1/S2/S3: {}",
            hits.len(),
            keys.join(",")
        ),
    ))
}

fn in_sublayer<'a>(all: &'a [FilterInfo], s: &GUID) -> Vec<&'a FilterInfo> {
    all.iter().filter(|f| &f.sublayer == s).collect()
}

/// Guard 3: refuse a sublayer that already holds any filter.
fn guard_sublayer_empty(all: &[FilterInfo], s: &GUID) -> Result<(), Refusal> {
    if toggled_off("nonempty") {
        return Ok(());
    }
    let n = in_sublayer(all, s).len();
    if n == 0 {
        Ok(())
    } else {
        Err(refuse(
            5,
            "sublayer_not_empty",
            format!("{} holds {n} filter(s)", guid_str(s)),
        ))
    }
}

// ───────────────────────────── output ─────────────────────────────────────────

fn emit(v: Value, code: i32) -> ! {
    println!("{v}");
    std::process::exit(code);
}

fn emit_refusal(r: &Refusal) -> ! {
    emit(
        json!({"ok": false, "error": "refused", "guard": r.guard, "detail": r.detail, "exit": r.exit}),
        r.exit,
    )
}

fn emit_usage(msg: &str) -> ! {
    emit(json!({"ok": false, "error": "usage", "detail": msg, "exit": 2}), 2)
}

fn emit_eng(phase: &str, e: &EngErr, write: bool, write_attempted: bool) -> ! {
    let elevated = is_elevated();
    let (code, label) = classify(elevated == Some(true), e, write);
    emit(
        json!({
            "ok": false,
            "error": label,
            "phase": phase,
            "write_attempted": write_attempted,
            "call": e.call,
            "rc": format!("0x{:08x}", e.rc),
            "elevated": elevated,
            "exit": code,
        }),
        code,
    )
}

fn version_json() -> Value {
    json!({
        "version": VERSION,
        "pinned_srt_win_sha": PINNED_SRT_WIN_SHA,
        "pinned_cargo_lock_sha256": PINNED_LOCK_SHA256.unwrap_or("unset"),
        "halfset_rs_sha256": EMBEDDED_RS_SHA256.unwrap_or("unset"),
        "toggle_build": cfg!(halfset_toggle),
    })
}

// ───────────────────────────── library wrappers (engine touches) ──────────────

fn lib_install(s: &GUID, sid: &str, range: (u16, u16)) -> Result<(), EngErr> {
    trace_engine_open("install_filters")?;
    #[cfg(halfset_toggle)]
    {
        let _ = (s, sid, range);
        return Err(EngErr::new("toggle_build_never_opens_engine", 0));
    }
    #[cfg(not(halfset_toggle))]
    srt_win::wfp::install_filters(s, sid, range).map_err(|e| EngErr::from_anyhow(&e))
}

fn lib_uninstall(s: &GUID) -> Result<usize, EngErr> {
    trace_engine_open("uninstall_filters")?;
    #[cfg(halfset_toggle)]
    {
        let _ = s;
        return Err(EngErr::new("toggle_build_never_opens_engine", 0));
    }
    #[cfg(not(halfset_toggle))]
    srt_win::wfp::uninstall_filters(s).map_err(|e| EngErr::from_anyhow(&e))
}

fn lib_status(s: &GUID) -> Result<srt_win::wfp::WfpStatus, EngErr> {
    trace_engine_open("filter_status")?;
    #[cfg(halfset_toggle)]
    {
        let _ = s;
        return Err(EngErr::new("toggle_build_never_opens_engine", 0));
    }
    #[cfg(not(halfset_toggle))]
    srt_win::wfp::filter_status(s).map_err(|e| EngErr::from_anyhow(&e))
}

// ───────────────────────────── argument parsing ───────────────────────────────

#[derive(Default)]
struct Args {
    sublayer: Option<String>,
    sid: Option<String>,
    range: Option<String>,
    key: Option<String>,
    live: Option<String>,
    all_ours: bool,
}

fn parse_args(rest: &[String]) -> Result<Args, String> {
    let mut a = Args::default();
    let mut i = 0;
    while i < rest.len() {
        let flag = rest[i].as_str();
        let mut take = |slot: &mut Option<String>| -> Result<(), String> {
            if slot.is_some() {
                return Err(format!("duplicate {flag}"));
            }
            i += 1;
            let v = rest.get(i).ok_or(format!("{flag} needs a value"))?;
            *slot = Some(v.clone());
            Ok(())
        };
        match flag {
            "--sublayer" => take(&mut a.sublayer)?,
            "--sid" => take(&mut a.sid)?,
            "--range" => take(&mut a.range)?,
            "--key" => take(&mut a.key)?,
            "--live" => take(&mut a.live)?,
            "--all-ours" => {
                if a.all_ours {
                    return Err("duplicate --all-ours".into());
                }
                a.all_ours = true;
            }
            other => return Err(format!("unknown argument {other}")),
        }
        i += 1;
    }
    Ok(a)
}

fn require_sublayer(a: &Args) -> GUID {
    let s = a
        .sublayer
        .as_deref()
        .unwrap_or_else(|| emit_usage("--sublayer is required"));
    parse_guid(s).unwrap_or_else(|e| emit_usage(&format!("{e:#}")))
}

fn forbid_extra(a: &Args, allowed: &[&str]) {
    let present = [
        ("sid", a.sid.is_some()),
        ("range", a.range.is_some()),
        ("key", a.key.is_some()),
        ("live", a.live.is_some()),
        ("all-ours", a.all_ours),
    ];
    for (n, p) in present {
        if p && !allowed.contains(&n) {
            emit_usage(&format!("--{n} is not valid for this subcommand"));
        }
    }
}

// ───────────────────────────── subcommands ────────────────────────────────────

fn open_or_exit(ctx: &str, write: bool, attempted: bool) -> Engine {
    Engine::open(ctx).unwrap_or_else(|e| emit_eng(ctx, &e, write, attempted))
}

/// Arming interlock; exits 12 unless the proof validates. Runs before any
/// engine open.
fn require_armed(a: &Args) {
    if let Err(r) = guard_armed(a.live.as_deref(), &own_exe_sha256, now_unix()) {
        emit_refusal(&r);
    }
}

/// Opens the engine, runs the sweep guard over the ALE layers and returns the
/// engine together with the enumerated filters.
fn open_and_sweep(ctx: &str, write: bool) -> (Engine, Vec<FilterInfo>) {
    let eng = open_or_exit(ctx, write, false);
    let all = eng
        .filters(Scope::Ale)
        .unwrap_or_else(|e| emit_eng(ctx, &e, write, false));
    if let Err(r) = guard_stop_sweep(&all) {
        emit_refusal(&r);
    }
    (eng, all)
}

fn cmd_install(a: &Args) -> ! {
    forbid_extra(a, &["sid", "range", "live"]);
    let s = require_sublayer(a);
    if let Err(r) = guard_sublayer(&s) {
        emit_refusal(&r);
    }
    let sid = a
        .sid
        .as_deref()
        .unwrap_or_else(|| emit_usage("--sid is required"));
    if let Err(r) = guard_install_sid(sid, &RealSidEnv) {
        emit_refusal(&r);
    }
    let range = match a.range.as_deref() {
        None => (60080u16, 60089u16),
        Some(r) => parse_port_range(r).unwrap_or_else(|e| emit_usage(&format!("{e:#}"))),
    };
    require_armed(a);
    {
        let (_eng, all) = open_and_sweep("install_precheck", true);
        if let Err(r) = guard_sublayer_empty(&all, &s) {
            emit_refusal(&r);
        }
    }
    if let Err(e) = lib_install(&s, sid, range) {
        emit_eng("install_filters", &e, true, true);
    }
    let eng = open_or_exit("install_readback", true, true);
    let all = eng
        .filters(Scope::Ale)
        .unwrap_or_else(|e| emit_eng("install_readback", &e, true, true));
    let here: Vec<Value> = in_sublayer(&all, &s).iter().map(|f| f.to_json()).collect();
    let ok = here.len() == srt_win::wfp::FILTER_COUNT;
    emit(
        json!({
            "ok": ok,
            "command": "install",
            "sublayer": guid_str(&s),
            "sid": sid,
            "range": [range.0, range.1],
            "readback_count": here.len(),
            "expected_count": srt_win::wfp::FILTER_COUNT,
            "filters": here,
            "exit": if ok { 0 } else { 8 },
        }),
        if ok { 0 } else { 8 },
    )
}

fn cmd_status(a: &Args) -> ! {
    forbid_extra(a, &[]);
    let s = require_sublayer(a);
    if let Err(r) = guard_sublayer(&s) {
        emit_refusal(&r);
    }
    match lib_status(&s) {
        Err(e) => emit_eng("filter_status", &e, false, false),
        Ok(st) => {
            let v = serde_json::to_value(&st).unwrap_or(Value::Null);
            if st.state == "cannot-read" {
                let elevated = is_elevated();
                let code = if elevated == Some(true) { 7 } else { 6 };
                emit(
                    json!({"ok": false, "error": "cannot_read", "elevated": elevated,
                           "srt_win_status": v, "exit": code}),
                    code,
                );
            }
            emit(json!({"ok": true, "srt_win_status": v, "exit": 0}), 0)
        }
    }
}

fn cmd_enum(a: &Args) -> ! {
    forbid_extra(a, &["all-ours"]);
    if a.all_ours {
        if a.sublayer.is_some() {
            emit_usage("--sublayer is not valid with --all-ours");
        }
        let eng = open_or_exit("enum_all_ours", false, false);
        let all = eng
            .filters(Scope::All)
            .unwrap_or_else(|e| emit_eng("enum_all_ours", &e, false, false));
        let mine: Vec<&FilterInfo> = all
            .iter()
            .filter(|f| sublayer_label(&f.sublayer).is_some() || matches_ours(f))
            .collect();
        let stops = stop_hits(&all);
        let code = if stops.is_empty() { 0 } else { 9 };
        emit(
            json!({
                "ok": stops.is_empty(),
                "command": "enum_all_ours",
                "scanned": all.len(),
                "count": mine.len(),
                "stop_count": stops.len(),
                "filters": mine.iter().map(|f| f.to_json()).collect::<Vec<_>>(),
                "stop_filters": stops.iter().map(|f| f.to_json()).collect::<Vec<_>>(),
                "exit": code,
            }),
            code,
        );
    }
    let s = require_sublayer(a);
    if let Err(r) = guard_sublayer(&s) {
        emit_refusal(&r);
    }
    let eng = open_or_exit("enum", false, false);
    let all = eng
        .filters(Scope::Ale)
        .unwrap_or_else(|e| emit_eng("enum", &e, false, false));
    let here = in_sublayer(&all, &s);
    emit(
        json!({
            "ok": true,
            "command": "enum",
            "sublayer": guid_str(&s),
            "sublayer_label": sublayer_label(&s),
            "count": here.len(),
            "filters": here.iter().map(|f| f.to_json()).collect::<Vec<_>>(),
            "exit": 0,
        }),
        0,
    )
}

fn cmd_delete_filter(a: &Args) -> ! {
    forbid_extra(a, &["key", "live"]);
    let s = require_sublayer(a);
    if let Err(r) = guard_sublayer(&s) {
        emit_refusal(&r);
    }
    let key = parse_guid(
        a.key
            .as_deref()
            .unwrap_or_else(|| emit_usage("--key is required")),
    )
    .unwrap_or_else(|e| emit_usage(&format!("{e:#}")));
    require_armed(a);
    let (eng, all) = open_and_sweep("delete_filter_precheck", true);
    let target = all.iter().find(|f| f.key == key && f.sublayer == s);
    let Some(target) = target else {
        emit(
            json!({"ok": false, "error": "target_not_under_sublayer",
                   "key": guid_str(&key), "sublayer": guid_str(&s), "exit": 11}),
            11,
        )
    };
    let before = target.to_json();
    let rc = eng.delete_filter(&key);
    if rc != 0 && rc != FWP_E_FILTER_NOT_FOUND {
        emit_eng("FwpmFilterDeleteByKey0", &EngErr::new("FwpmFilterDeleteByKey0", rc), true, true);
    }
    let after = eng
        .filters(Scope::Ale)
        .unwrap_or_else(|e| emit_eng("delete_filter_readback", &e, true, true));
    let still = after.iter().any(|f| f.key == key);
    let code = if still { 8 } else { 0 };
    emit(
        json!({"ok": !still, "command": "delete-filter", "key": guid_str(&key),
               "sublayer": guid_str(&s), "deleted_filter": before,
               "absent_after": !still, "exit": code}),
        code,
    )
}

/// Deletes the sublayer once it is empty and verifies absence. Shared by
/// `delete-sublayer` and `uninstall`.
fn delete_sublayer_checked(
    eng: &Engine,
    s: &GUID,
    command: &str,
    extra: Value,
    write_attempted: bool,
) -> ! {
    let all = eng
        .filters(Scope::Ale)
        .unwrap_or_else(|e| emit_eng(command, &e, true, write_attempted));
    if let Err(r) = guard_sublayer_empty(&all, s) {
        emit(
            json!({"ok": false, "error": "refused", "guard": r.guard, "detail": r.detail,
                   "command": command, "extra": extra, "exit": r.exit}),
            r.exit,
        );
    }
    let rc = eng.delete_sublayer(s);
    let already_absent = rc == FWP_E_SUBLAYER_NOT_FOUND;
    if rc == FWP_E_IN_USE {
        emit(
            json!({"ok": false, "error": "refused", "guard": "sublayer_not_empty",
                   "detail": "engine reports the sublayer in use (a filter exists at a layer outside the ALE connect layers)",
                   "command": command, "extra": extra, "exit": 5}),
            5,
        );
    }
    if rc != 0 && !already_absent {
        emit_eng("FwpmSubLayerDeleteByKey0", &EngErr::new("FwpmSubLayerDeleteByKey0", rc), true, true);
    }
    let exists = eng
        .sublayer_exists(s)
        .unwrap_or_else(|e| emit_eng("sublayer_readback", &e, true, true));
    let code = if exists { 8 } else { 0 };
    emit(
        json!({"ok": !exists, "command": command, "sublayer": guid_str(s),
               "already_absent": already_absent, "absent_after": !exists,
               "extra": extra, "exit": code}),
        code,
    )
}

fn cmd_delete_sublayer(a: &Args) -> ! {
    forbid_extra(a, &["live"]);
    let s = require_sublayer(a);
    if let Err(r) = guard_sublayer(&s) {
        emit_refusal(&r);
    }
    require_armed(a);
    let (eng, _all) = open_and_sweep("delete_sublayer_precheck", true);
    delete_sublayer_checked(&eng, &s, "delete-sublayer", Value::Null, false)
}

fn cmd_uninstall(a: &Args) -> ! {
    forbid_extra(a, &["live"]);
    let s = require_sublayer(a);
    if let Err(r) = guard_sublayer(&s) {
        emit_refusal(&r);
    }
    require_armed(a);
    {
        let (_eng, _all) = open_and_sweep("uninstall_precheck", true);
    }
    let deleted = match lib_uninstall(&s) {
        Ok(n) => n,
        Err(e) => emit_eng("uninstall_filters", &e, true, true),
    };
    let eng = open_or_exit("uninstall_sublayer", true, true);
    delete_sublayer_checked(
        &eng,
        &s,
        "uninstall",
        json!({"srt_win_tagged_deleted": deleted}),
        true,
    )
}

// ───────────────────────────── selftest-refusals ──────────────────────────────

struct FakeEnv {
    op: Result<String, String>,
    groups: Result<Vec<String>, String>,
    lookup: Result<String, String>,
    exist: Result<SidExistence, String>,
}

impl FakeEnv {
    fn good() -> Self {
        Self {
            op: Ok("S-1-5-21-1-2-3-1001".into()),
            groups: Ok(vec!["S-1-5-21-1-2-3-513".into(), "S-1-5-32-544".into()]),
            lookup: Ok(SPIKE_SID.into()),
            exist: Ok(SidExistence::Unmapped),
        }
    }
}
impl SidEnv for FakeEnv {
    fn operator_sid(&self) -> Result<String, String> {
        self.op.clone()
    }
    fn token_group_sids(&self) -> Result<Vec<String>, String> {
        self.groups.clone()
    }
    fn lookup_account(&self, _: &str) -> Result<String, String> {
        self.lookup.clone()
    }
    fn existence(&self, _: &str) -> Result<SidExistence, String> {
        self.exist.clone()
    }
}

fn fake_filter(sublayer: GUID, name: &str, tool: Option<&str>) -> FilterInfo {
    FilterInfo {
        key: GUID::from_u128(0x1111_2222_3333_4444_5555_6666_7777_8888),
        layer: FWPM_LAYER_ALE_AUTH_CONNECT_V4,
        sublayer,
        name: name.into(),
        tool: tool.map(String::from),
        kind: None,
        user_sid: None,
        port_range: None,
        has_user_condition: false,
        num_conditions: 0,
        action: FWP_ACTION_BLOCK.0,
        weight: None,
    }
}

struct Checks(Vec<Value>);
impl Checks {
    fn expect(&mut self, name: &str, got: Result<(), Refusal>, want_exit: Option<i32>) {
        let (ok, detail) = match (&got, want_exit) {
            (Ok(()), None) => (true, "allowed".to_string()),
            (Err(r), Some(c)) if r.exit == c => (true, format!("refused exit {}: {}", r.exit, r.guard)),
            (Ok(()), Some(c)) => (false, format!("allowed but expected refusal exit {c}")),
            (Err(r), None) => (false, format!("refused exit {} ({}) but expected allow", r.exit, r.detail)),
            (Err(r), Some(c)) => (false, format!("refused exit {} but expected {c}", r.exit)),
        };
        self.0.push(json!({"check": name, "ok": ok, "detail": detail}));
    }
    fn truth(&mut self, name: &str, ok: bool, detail: &str) {
        self.0.push(json!({"check": name, "ok": ok, "detail": detail}));
    }
}

fn cmd_selftest() -> ! {
    let mut c = Checks(Vec::new());
    let before = ENGINE_OPENS.load(Ordering::SeqCst);

    // Guard 1.
    for (g, n) in [(S1, "S1"), (S2, "S2"), (S3, "S3")] {
        c.expect(&format!("sublayer_{n}_allowed"), guard_sublayer(&g), None);
    }
    c.expect("sublayer_srt_default_refused", guard_sublayer(&SRT_DEFAULT_SUBLAYER), Some(3));
    c.expect("sublayer_old_arm3_refused", guard_sublayer(&OLD_ARM3_SUBLAYER), Some(3));
    c.expect("sublayer_zero_refused", guard_sublayer(&GUID::zeroed()), Some(3));
    c.expect(
        "sublayer_random_refused",
        guard_sublayer(&GUID::from_u128(0xdeadbeef_0000_4000_8000_000000000001)),
        Some(3),
    );
    let parsed = parse_guid("{C971A69F-D6AB-4885-9B49-506D8AA51C86}");
    c.truth(
        "sublayer_braced_uppercase_parses_to_S1",
        parsed.map(|g| g == S1).unwrap_or(false),
        "parse_guid canonicalises case and braces before the allowlist compare",
    );

    // Guard 2.
    let good = FakeEnv::good();
    c.expect("sid_spike_allowed", guard_install_sid(SPIKE_SID, &good), None);
    c.expect("sid_stale_allowed_when_unmapped", guard_install_sid(STALE_SID, &good), None);
    let op = good.op.clone().unwrap();
    c.expect("sid_operator_refused", guard_install_sid(&op, &good), Some(4));
    c.expect("sid_token_group_refused", guard_install_sid("S-1-5-21-1-2-3-513", &good), Some(4));
    c.expect("sid_token_group_builtin_admins_refused", guard_install_sid("S-1-5-32-544", &good), Some(4));
    for w in ["S-1-1-0", "S-1-5-18", "S-1-5-11", "S-1-5-32-545", "S-1-5-4"] {
        c.expect(&format!("sid_wellknown_{w}_refused"), guard_install_sid(w, &good), Some(4));
    }
    for g in ["", "garbage", "S-1-5-21-9-9-9-9999", &SPIKE_SID.to_ascii_lowercase(), " S-1-5-21-1000000001-1000000002-1000000003-1271"] {
        c.expect(&format!("sid_other_refused[{g}]"), guard_install_sid(g, &good), Some(4));
    }
    let mut e = FakeEnv::good();
    e.lookup = Ok("S-1-5-21-1000000001-1000000002-1000000003-1272".into());
    c.expect("sid_spike_lookup_mismatch_refused", guard_install_sid(SPIKE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.lookup = Err("not found".into());
    c.expect("sid_spike_lookup_error_refused", guard_install_sid(SPIKE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.exist = Ok(SidExistence::Mapped);
    c.expect("sid_stale_mapped_refused", guard_install_sid(STALE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.exist = Ok(SidExistence::Unknown);
    c.expect("sid_stale_unknown_refused", guard_install_sid(STALE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.exist = Err("rpc".into());
    c.expect("sid_stale_lookup_error_refused", guard_install_sid(STALE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.op = Ok(SPIKE_SID.into());
    c.expect("sid_spike_equal_to_caller_refused", guard_install_sid(SPIKE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.groups = Ok(vec![STALE_SID.into()]);
    c.expect("sid_stale_in_caller_groups_refused", guard_install_sid(STALE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.op = Err("token".into());
    c.expect("sid_caller_user_unreadable_refused", guard_install_sid(SPIKE_SID, &e), Some(4));
    let mut e = FakeEnv::good();
    e.groups = Err("token".into());
    c.expect("sid_caller_groups_unreadable_refused", guard_install_sid(SPIKE_SID, &e), Some(4));

    // Guard 3 and the stop sweep.
    let empty: Vec<FilterInfo> = vec![];
    c.expect("nonempty_empty_allowed", guard_sublayer_empty(&empty, &S2), None);
    let one = vec![fake_filter(S2, "BlarAI #1763 x", None)];
    c.expect("nonempty_one_filter_refused", guard_sublayer_empty(&one, &S2), Some(5));
    let other = vec![fake_filter(S1, "unrelated", None)];
    c.expect("nonempty_other_sublayer_allowed", guard_sublayer_empty(&other, &S2), None);
    let untagged = vec![fake_filter(S3, "plain", None)];
    c.expect("nonempty_untagged_filter_refused", guard_sublayer_empty(&untagged, &S3), Some(5));

    c.expect("sweep_clean_allowed", guard_stop_sweep(&[fake_filter(GUID::from_u128(7), "Windows rule", None)]), None);
    c.expect("sweep_ours_in_S1_S2_S3_allowed", guard_stop_sweep(&[fake_filter(S2, "BlarAI #1763 y", None), fake_filter(S1, "srt-win-v4-block-user", Some("srt-win"))]), None);
    c.expect("sweep_name_srt_win_elsewhere_stops", guard_stop_sweep(&[fake_filter(GUID::from_u128(7), "srt-win-v4-block-user", None)]), Some(9));
    c.expect("sweep_name_marker_elsewhere_stops", guard_stop_sweep(&[fake_filter(GUID::from_u128(7), "my BlarAI #1763 thing", None)]), Some(9));
    c.expect("sweep_tag_tool_elsewhere_stops", guard_stop_sweep(&[fake_filter(GUID::from_u128(7), "renamed", Some("srt-win"))]), Some(9));
    c.expect("sweep_default_sublayer_stops", guard_stop_sweep(&[fake_filter(SRT_DEFAULT_SUBLAYER, "x", None)]), Some(9));
    c.expect("sweep_old_arm3_sublayer_stops", guard_stop_sweep(&[fake_filter(OLD_ARM3_SUBLAYER, "x", None)]), Some(9));

    // Arming interlock (exit 12).
    c.truth(
        "sha256_empty_vector",
        sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "FIPS 180-4 empty message",
    );
    c.truth(
        "sha256_abc_vector",
        sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "FIPS 180-4 'abc'",
    );
    c.truth(
        "sha256_two_block_vector",
        sha256_hex(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")
            == "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
        "FIPS 180-4 448-bit message",
    );
    let exe_sha = "a".repeat(64);
    let rs_sha = "b".repeat(64);
    let now = parse_utc("2026-10-12T20:00:00Z").unwrap_or(0);
    c.truth("utc_parse_known_value", now == 1_791_835_200, "2026-10-12T20:00:00Z");
    c.truth(
        "utc_parse_offset_form",
        parse_utc("2026-10-12T16:00:00-04:00") == Some(now),
        "numeric offset",
    );
    let proof = |schema: &str, exe: &str, rs: &str, failed: &str, when: &str| -> String {
        format!(
            "{{\"schema\":\"{schema}\",\"halfset_exe_sha256\":\"{exe}\",\"halfset_rs_sha256\":\"{rs}\",\"checks_failed\":{failed},\"written_utc\":\"{when}\"}}"
        )
    };
    let good_p = proof(PROOF_SCHEMA, &exe_sha, &rs_sha, "0", "2026-10-12T19:00:00Z");
    let arm = |text: &str, rs: Option<&str>, exe: &str| -> Result<(), Refusal> {
        if toggled_off("interlock") {
            return Ok(());
        }
        check_proof(text, exe, rs, now).map_err(|e| refuse(12, "not_armed", e))
    };
    c.expect("arm_valid_proof_accepted", arm(&good_p, Some(&rs_sha), &exe_sha), None);
    c.expect(
        "arm_wrong_schema_refused",
        arm(&proof("nep5-1763-proof-v0", &exe_sha, &rs_sha, "0", "2026-10-12T19:00:00Z"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect(
        "arm_wrong_exe_hash_refused",
        arm(&proof(PROOF_SCHEMA, &"c".repeat(64), &rs_sha, "0", "2026-10-12T19:00:00Z"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect(
        "arm_wrong_source_hash_refused",
        arm(&proof(PROOF_SCHEMA, &exe_sha, &"c".repeat(64), "0", "2026-10-12T19:00:00Z"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect(
        "arm_checks_failed_nonzero_refused",
        arm(&proof(PROOF_SCHEMA, &exe_sha, &rs_sha, "1", "2026-10-12T19:00:00Z"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect(
        "arm_checks_failed_string_refused",
        arm(&proof(PROOF_SCHEMA, &exe_sha, &rs_sha, "\"0\"", "2026-10-12T19:00:00Z"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect(
        "arm_stale_proof_refused",
        arm(&proof(PROOF_SCHEMA, &exe_sha, &rs_sha, "0", "2026-10-11T19:59:00Z"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect(
        "arm_future_proof_refused",
        arm(&proof(PROOF_SCHEMA, &exe_sha, &rs_sha, "0", "2026-10-12T21:00:00Z"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect(
        "arm_no_zone_timestamp_refused",
        arm(&proof(PROOF_SCHEMA, &exe_sha, &rs_sha, "0", "2026-10-12T19:00:00"), Some(&rs_sha), &exe_sha),
        Some(12),
    );
    c.expect("arm_not_json_refused", arm("not json", Some(&rs_sha), &exe_sha), Some(12));
    c.expect("arm_build_without_source_hash_refused", arm(&good_p, None, &exe_sha), Some(12));
    c.expect(
        "arm_missing_token_refused",
        guard_armed(None, &|| Ok(exe_sha.clone()), now),
        Some(12),
    );
    c.expect(
        "arm_unreadable_proof_path_refused",
        guard_armed(Some("C:/nonexistent-halfset-proof-path/proof.json"), &|| Ok(exe_sha.clone()), now),
        Some(12),
    );

    // Guard 1 input forms: srt-win's parse_guid strips braces independently.
    for form in [
        "{c971a69f-d6ab-4885-9b49-506d8aa51c86",
        "c971a69f-d6ab-4885-9b49-506d8aa51c86}",
        "{{c971a69f-d6ab-4885-9b49-506d8aa51c86}}",
    ] {
        c.truth(
            &format!("sublayer_unbalanced_braces_parse_to_S1[{form}]"),
            parse_guid(form).map(|g| g == S1).unwrap_or(false),
            "pinned: unbalanced braces are accepted and resolve to the same GUID the allowlist compares",
        );
    }

    // Guard 4: exit classification.
    let denied = EngErr::new("FwpmEngineOpen0", FWP_E_ACCESS_DENIED);
    let denied5 = EngErr::new("FwpmFilterEnum0", ERROR_ACCESS_DENIED);
    let other_rc = EngErr::new("FwpmFilterEnum0", 0x8032_0001);
    c.truth("classify_nonelevated_read_denied_is_6", classify(false, &denied, false) == (6, "not_elevated") && classify(false, &denied5, false).0 == 6, "exit 6 for an unreadable engine without elevation");
    c.truth("classify_nonelevated_write_denied_is_7", classify(false, &denied, true) == (7, "engine_denied"), "exit 7, code recorded verbatim");
    c.truth("classify_elevated_denied_is_7", classify(true, &denied, false).0 == 7, "elevated denial is 7");
    c.truth(
        "classify_trace_failure_is_13_not_engine_error",
        classify(true, &EngErr::new("trace_open_failed", 0), true) == (13, "trace_failed")
            && classify(false, &EngErr::new("trace_write_failed", 0), false).0 == 13,
        "a trace file that cannot be written is not an engine error",
    );
    c.truth("classify_other_rc_is_10", classify(true, &other_rc, true).0 == 10 && classify(false, &other_rc, false).0 == 10, "non-denial engine failure is 10");

    // Guard 5: embedded version data.
    let lock_ok = PINNED_LOCK_SHA256
        .map(|h| h.len() == 64 && h.bytes().all(|b| b.is_ascii_hexdigit()))
        .unwrap_or(false);
    c.truth("version_embeds_pinned_lock_sha256", lock_ok, PINNED_LOCK_SHA256.unwrap_or("unset"));
    let rs_ok = EMBEDDED_RS_SHA256.map(is_sha256_hex).unwrap_or(false);
    c.truth("version_embeds_halfset_rs_sha256", rs_ok, EMBEDDED_RS_SHA256.unwrap_or("unset"));
    c.truth("version_embeds_pinned_sha", PINNED_SRT_WIN_SHA.len() == 40, PINNED_SRT_WIN_SHA);

    // Constants.
    c.truth(
        "constants_distinct",
        S1 != S2 && S2 != S3 && S1 != S3 && !ALLOWED_SUBLAYERS.iter().any(|(g, _)| FORBIDDEN_SUBLAYERS.contains(g)),
        "S1/S2/S3 distinct and disjoint from the forbidden sublayers",
    );

    // No engine open happened.
    let opens = ENGINE_OPENS.load(Ordering::SeqCst) - before;
    c.truth("no_engine_open_during_selftest", opens == 0, &format!("{opens} engine touch(es)"));

    let failed = c.0.iter().filter(|v| v["ok"] == json!(false)).count();
    let code = if failed == 0 { 0 } else { 1 };
    emit(
        json!({"ok": failed == 0, "command": "selftest-refusals", "total": c.0.len(),
               "failed": failed, "engine_opens": opens, "checks": c.0, "exit": code}),
        code,
    )
}

// ───────────────────────────── main ───────────────────────────────────────────

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = argv.first() else {
        emit_usage("subcommand required: install|status|enum|delete-filter|delete-sublayer|uninstall|selftest-refusals|--version")
    };
    if cmd == "--version" {
        if argv.len() != 1 {
            emit_usage("--version takes no arguments");
        }
        emit(version_json(), 0);
    }
    if cmd == "selftest-refusals" {
        if argv.len() != 1 {
            emit_usage("selftest-refusals takes no arguments");
        }
        cmd_selftest();
    }
    let args = parse_args(&argv[1..]).unwrap_or_else(|m| emit_usage(&m));
    match cmd.as_str() {
        "install" => cmd_install(&args),
        "status" => cmd_status(&args),
        "enum" => cmd_enum(&args),
        "delete-filter" => cmd_delete_filter(&args),
        "delete-sublayer" => cmd_delete_sublayer(&args),
        "uninstall" => cmd_uninstall(&args),
        other => emit_usage(&format!("unknown subcommand {other}")),
    }
}
