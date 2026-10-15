"""Locks for the operator-run Codex sandbox removal (#1743), run in the standing gate.

Three layers, none of which needs elevation or touches an account, rule or registry value:
  1. Structural: the script is parsed by PowerShell and the apply path, every refusal and every identity
     check (account SID, group members, rule scope, name allowlists, delete-by-SID) must appear in its own
     function in the expected order. Each pattern has at least one planted single-line removal
     (``test_structural_check_rejects_each_planted_violation``) that must be rejected.
  2. Behavioural: tests/security/remove_codex_sandbox_cheap_checks.ps1 runs the pure helpers and one tiny
     throwaway tree under C:\\blarai-spike-1740-ops (the object's own list is edited, nothing else), and
     ``test_cheap_checks_fail_on_each_broken_copy_of_the_script`` runs it against deliberately broken copies
     of the script: every one must make a check fail.
  3. The script's own throwaway-account self-test (``remove_codex_sandbox.ps1 -SelfTest``: elevated, about
     15 minutes, creates and removes zz1740-<token>-* accounts, rules and folders) is NOT part of the gate.
     ``pytest -m slow`` with BLARAI_OPERATOR_SELFTEST=1 in an elevated shell runs it; run it before the
     operator uses the script.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PS1 = _ROOT / "tools" / "operator" / "remove_codex_sandbox.ps1"
_CMD = _ROOT / "tools" / "operator" / "remove_codex_sandbox.cmd"
_PWSH = shutil.which("pwsh")

# Built-in aliases a function name must never equal: the alias wins at call time, so a
# helper named Rd runs Remove-Item (an earlier probe deleted a tracked file this way).
_ALIASES = frozenset(
    "ac asnp cat cd chdir clc clear clhy cli clp cls clv cnsn compare copy cp cpi cpp curl cvpa dbp del diff dir dnsn ebp echo epal epcsv epsn erase etsn exsn fc fhx fl foreach ft fw gal gbp gc gcb gci gcm gcs gdr gerr ghy gi gin gjb gl gm gmo gp gps gpv group gsn gsnp gsv gtz gu gv gwmi h history icm iex ihy ii ipcsv ipmo ipsn irm ise iwr kill lp ls man md measure mi mkdir mount move mp mv nal ndr ni nmo npssc nsn nv ogv oh popd ps pushd pwd r rbp rcjb rcsn rd rdr ren ri rjb rm rmdir rmo rni rnp rp rsn rv rvpa rwmi sajb sal saps sasv sbp sc select set shcm si sl sleep sls sort sp spjb spps spsv start stz sv swmi tee type where wget write".split()
)


def alias_collisions(text: str) -> list[str]:
    names = re.findall(r"(?im)^\s*function\s+(?:script:|global:)?([A-Za-z0-9_-]+)", text)
    return sorted({n for n in names if n.lower() in _ALIASES})


def non_ascii(data: bytes) -> bool:
    return any(b > 0x7F for b in data)


_STUB = _ROOT / "tools" / "operator" / "remove_codex_sandbox_launch_stub.ps1"


def _stub_of(cmd: str) -> str | None:
    m = re.search(r"'-EncodedCommand','([A-Za-z0-9+/=]+)'", cmd)
    return base64.b64decode(m.group(1)).decode("utf-16-le") if m else None


def _with_stub(cmd: str, stub: str) -> str:
    return re.sub(r"('-EncodedCommand',')[A-Za-z0-9+/=]+(')", lambda m: m.group(1) + base64.b64encode(stub.encode("utf-16-le")).decode("ascii") + m.group(2), cmd)


def launcher_problems(cmd: str) -> list[str]:
    """The double-click launcher: hash read before approval, elevated stub copies to a protected folder and checks the hash."""
    out = []
    stub = _stub_of(cmd)
    if "-NoExit" in cmd:
        out.append("elevated window keeps -NoExit, so its exit code is never shown")
    if "-ErrorAction Stop" not in cmd or "catch" not in cmd:
        out.append("a cancelled UAC prompt is not caught")
    if not re.search(r"(?im)^if errorlevel 1 \(", cmd) or "pause" not in cmd.split("if errorlevel 1", 1)[-1]:
        out.append("no pause after a failed launch, so the window closes unread")
    if "SHA256" not in cmd or "-eq 13" not in cmd or "RCS_SHA" not in cmd or "echo Script SHA-256: %RCS_SHA%" not in cmd:
        out.append("the launcher does not read and print the script hash (line endings normalised) before approval")
    if stub is None:
        out.append("no encoded elevated step")
        return out
    for need in ("-HoldOpen", "-ExpectScriptSha256", "run-1743", "Hash of the protected copy", "REFUSED: the script changed", "SetAccessRuleProtection($true, $false)", "S-1-5-32-544", "-Guided -Stage Accounts", "AreAccessRulesProtected", "ReparsePoint", "-ne $want"):
        if need not in stub:
            out.append(f"the elevated step lacks {need!r}")
    if "-NoExit" in stub:
        out.append("the elevated step keeps -NoExit")
    return out


# ---------------------------------------------------------------- syntax-tree extraction


def _load_functions() -> dict[str, str]:
    """Function name -> body text, taken from the PowerShell parser (not from regexes)."""
    code = (
        "$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile("
        f"'{_PS1}',[ref]$t,[ref]$e); if ($e.Count) {{ exit 3 }};"
        "$ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)"
        "| ForEach-Object { [pscustomobject]@{ n=$_.Name; b=$_.Body.Extent.Text } } | ConvertTo-Json -Depth 3 -Compress"
    )
    done = subprocess.run([_PWSH, "-NoProfile", "-Command", code], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    return {f["n"]: f["b"].replace("\r\n", "\n") for f in json.loads(done.stdout)}


def _entry_block(ps1: str) -> str:
    return ps1.split("if ($MyInvocation.InvocationName -ne '.')", 1)[-1]


def _in_order(body: str, patterns: list[str]) -> str | None:
    pos = -1
    for pat in patterns:
        m = re.compile(pat, re.S).search(body, pos + 1)
        if not m:
            return pat
        pos = m.start()
    return None


def structural_problems(fn: dict[str, str], ps1: str) -> list[str]:
    out: list[str] = []

    def need(name: str, patterns: list[str], what: str) -> None:
        body = fn.get(name)
        if body is None:
            out.append(f"{name} is missing ({what})")
            return
        miss = _in_order(body, patterns)
        if miss:
            out.append(f"{name}: {what} - expected, in order: {miss}")

    # the apply path: every refusal before the first change, irreversible steps after the full read-back
    need(
        "Invoke-Apply",
        [
            r"Assert-Elevated \$IsAdmin",
            r"if \(\$hasAcl -and \(\$Spec\.Mode -ceq 'real'\) -and \(Test-Gate 'acl-stage-blocked'\)\) \{\s*Refuse 'acl-stage-blocked'",
            r"Assert-SpecAllowed \$Spec",
            r"Invoke-DryRun \$Spec \$IsAdmin \$Stage",
            r"if \(\$pre\.Findings\.Count\) \{ Refuse 'unexpected-live'",
            r"Test-Gate 'plan-digest'",
            r"IsNullOrEmpty\(\$ExpectPlan\)\) \{ Refuse 'plan-digest'",
            r"\$ExpectPlan -cne \$pre\.Digest\) \{ Refuse 'plan-digest'",
            r"if \(\$hasAcl\) \{ \$resume = Resolve-ResumeBaseline",
            r"Write-Backup \$Spec",
            r"Get-StepAbsent \$Spec \$now \$s\)\) \{ throw",
            r"& \$runSteps @\(\$pre\.Plan \| Where-Object \{ \$_\.kind -ceq 'acl' \}\)",
            r"\$hasAcl -and \$res\.code -eq 0 -and -not \$script:SimulateOnly",
            r"Invoke-TreeScans",
            r"Get-CertificationProblems",
            r"if \(Test-Gate 'collateral-stop'\) \{ \$cert \+=",
            r"if \(\$cert\.Count\) \{\s*\$res\.code = 1",
            r"if \(\$res\.code -eq 0\) \{ & \$runSteps @\(\$pre\.Plan \| Where-Object \{ \$_\.kind -cne 'acl' \}\) \}",
            r"\$res\.ok = Get-ApplyVerdict \$res\.code \$left \$cert",
        ],
        "the order of the apply path",
    )
    need(
        "Assert-SpecAllowed",
        [r"Test-Gate 'spec-real-pinned'\) -and \(\(Get-SpecDigest \$Spec\) -cne \$script:RealSpecPin\)\) \{\s*Refuse 'spec-real-pinned'"],
        "the spec pin refusal",
    )
    if not re.search(r"\$script:RealSpecPin = '[0-9a-f]{64}'", ps1):
        out.append("the real spec pin is not a 64-hex digest")
    need(
        "Get-CertificationProblems",
        [r"Test-Gate 'scan-complete'\) -and \(\$sc\.foldersLeftUnscanned -gt 0 -or \$sc\.unreadable -gt 0\)\) \{\s*\$p\.Add"],
        "a cut-short or unreadable scan cannot certify",
    )
    need(
        "Get-Findings",
        [r"Test-Gate 'unexpected-live'\)\) \{ return @\(\) \}", r"if \(-not \$h\.checked\) \{ foreach \(\$n in \$h\.notRun\) \{ \$f\.Add"],
        "a check that did not run raises a finding",
    )
    # stage 1 (Accounts) reads and changes no access list: every access-list path is behind the stage test
    need("Write-Backup", [r"if \(Test-StageHas \$Stage 'Acl'\) \{ foreach", r"if \(Test-StageHas \$Stage 'Acl'\) \{ \$script:LastSnapshot = Write-TreeSnapshot"], "no snapshot or access-list backup for stage 1")
    need("Get-LiveState", [r"\$\(if \(Test-StageHas \$Stage 'Acl'\) \{ @\(\$Spec\.AclTargets"], "no access-list read for stage 1")
    need("Get-Plan", [r"\$\(if \(Test-StageHas \$Stage 'Acl'\) \{ \$Spec\.AclTargets", r"if \(-not \(Test-StageHas \$Stage 'Accounts'\)\) \{ return"], "stage-aware plan")
    need("Test-StageHas", [r"\$st = \"\$Stage\"\.ToLowerInvariant\(\)", r"-cnotcontains \$st\) \{ throw", r"'Accounts' \{ return \(\$st -ceq 'accounts'\) -or \(\$st -ceq 'all'\) \}", r"'Acl' \{ return \(\$st -ceq 'aclentries'\) -or \(\$st -ceq 'all'\) \}"], "stage coverage, any letter case, unknown refused")
    need("Get-CanonicalStage", [r"ToLowerInvariant", r"default \{ throw"], "canonical stage name")
    need("Get-PlanDigest", [r"stage=\$\(Get-CanonicalStage \$Stage\)", r"script=\$\(Get-ScriptSha256\)"], "the digest is bound to the stage and to the script")
    need("Get-ScriptSha256", [r"Get-NormalisedSha256 \$script:SelfPath"], "the script's own hash")
    need("Test-ScopeOnlySid", [r"Get-AceInfo \$LocalUser", r"\$aces\.Count -eq 1\) -and \(\$aces\[0\]\.Type -ceq 'A'\) -and \(\$aces\[0\]\.Sid -ceq \$Sid\)"], "a scope is exactly one allow entry for the pinned SID, whatever its form")
    need("Get-LocalUserOrNull", [r"-ErrorAction Stop\ncatch|-ErrorAction Stop \} catch \[Microsoft\.PowerShell\.Commands\.UserNotFoundException\] \{ return \$null \}"], "only 'not found' reads as absent")
    need("Get-LocalGroupOrNull", [r"-ErrorAction Stop \} catch \[Microsoft\.PowerShell\.Commands\.GroupNotFoundException\] \{ return \$null \}"], "only 'not found' reads as absent")
    need("Get-FirewallRulesByDisplayName", [r"-ErrorAction Stop", r"ObjectNotFound", r"\n\s*throw\n"], "only 'not found' reads as no rules")
    need("Get-UserState", [r"Get-LocalUserOrNull"], "account read")
    need("Get-GroupState", [r"Get-LocalGroupOrNull"], "group read")
    need("Get-FirewallRuleState", [r"Get-FirewallRulesByDisplayName"], "rule read")
    need("Get-LiveState", [r"Win32_UserProfile -ErrorAction Stop", r"Get-FirewallRulesByDisplayName"], "profile and extra-rule reads stop on error")
    need("Get-HeavyState", [r"Get-Service -ErrorAction Stop", r"Get-ScheduledTask -ErrorAction Stop"], "service and task reads stop on error")
    need("Get-Findings", [r"\$u\.sid -cne \$u\.expectedSid", r"\$g\.description -cne", r"\$allowed -cnotcontains \$m", r"\$r\.count -gt 1", r"\$r\.name -cne \$r\.expectedName", r"Test-ScopeOnlySid \(\[string\]\$r\.localUser\) \$want"], "identity findings")
    need("Invoke-Main", [r"\(\$Guided\) -and \(Test-StageHas \$Stage 'Acl'\) -and \(Test-Gate 'acl-stage-blocked'\)"], "-Guided never offers the access-entry stage on the real machine")
    need("Assert-Elevated", [r"Test-Gate 'elevation'\) -and -not \$IsAdmin\) \{ Refuse 'elevation'"], "elevation refusal")
    for gate in ("tree-snapshot", "snapshot-unreadable", "codex-below-root", "scan-only-sid", "empty-after"):
        need("Write-TreeSnapshot", [rf"Test-Gate '{gate}'\).{{0,200}}?\{{\s*Refuse '{gate}'"], f"refusal {gate}")
    # the access-entry stage: one object, one handle, the kernel call, nothing re-derived
    need(
        "Remove-ObjectSids",
        [
            r"\[OpAcl\]::Open\(\$Path\)",
            r"Test-Gate 'acl-handle'\) \{",
            r"\[OpAcl\]::Inspect\(\$h\)",
            r"\$i\.FinalPath -ine \('\\\\\?\\' \+ \$Path\)\) \{ return \"refused",
            r"\$i\.Links -gt 1",
            r"\[OpAcl\]::LinkNames\(\$Path\)",
            r"if \(\$outside\.Count\) \{ return \"refused",
            r"\[OpAcl\]::GetSddl\(\$h\)",
            r"Remove-SidsFromSddl \$old \$Sids",
            r"Test-Gate 'empty-after'\) -and -not \(Test-SddlHasAces \$new\)\) \{ return 'refused",
            r"ConvertTo-WritableSddl \$new",
            r"\[OpAcl\]::SetSddl\(\$handle, \$write\)",
            r"if \(\$back -cne \$new\) \{ return \"failed",
        ],
        "one object, one handle, nothing re-derived, written and read back",
    )
    need(
        "Remove-SidAcesTree",
        [
            r"Assert-SpecAllowed \$Spec",
            r"Test-Gate 'name-allowlist'\) \{ Refuse 'name-allowlist'",
            r"Test-Gate 'acl-reparse'\) -and",
            r"\$roots = Get-LinkNameRoots \$Spec",
            r"Remove-ObjectSids \$p \$scope \$roots",
            r"if \(\$problems\.Count -or \$n\.left\) \{\s*throw",
        ],
        "the tree walk",
    )
    if re.search(r"extern[^;]*\b(SetSecurityInfo|SetNamedSecurityInfoW?|TreeSetNamedSecurityInfoW?)\(", ps1):
        out.append("the native code writes an access list with a call that re-derives or propagates inherited entries")
    for fname, body in fn.items():
        if fname in ("Invoke-SelfTest", "New-Fixture", "Remove-Throwaway", "New-AdminOnlyDirectory"):
            continue
        if re.search(r"\.(PurgeAccessRules|SetAccessRuleProtection|SetAccessControl)\(|\bSet-Acl\b", body):
            out.append(f"{fname} writes an access list in a way that re-derives or propagates inherited entries")
    if "NtSetSecurityObject(h, DACL_SECURITY_INFORMATION, sd)" not in ps1:
        out.append("the access-list write is not the kernel call")
    need(
        "Invoke-RestoreAcl",
        [
            r"Assert-Elevated \$IsAdmin",
            r"Assert-SpecAllowed \$Spec",
            r"Assert-AdminOnlyDirectory \$Dir",
            r"Test-Gate 'restore-baseline'\) -and \(\(Get-FileHash",
            r"Test-Gate 'restore-path'\) -and",
            r"Test-Gate 'acl-handle'\) -and \(\$info\.FinalPath -ine",
        ],
        "restore from a protected, hash-checked backup, inside the allowlist only",
    )
    need(
        "Resolve-ResumeBaseline",
        [
            r"Test-Gate 'resume-required'\)\) \{\s*Refuse 'resume-required'",
            r"Refuse 'resume-target'",
            r"Assert-AdminOnlyDirectory \$full",
            r"Test-Gate 'resume-baseline'\) -and \(\(Get-FileHash",
        ],
        "an unfinished earlier apply must be resumed from its own protected, hash-checked snapshot",
    )
    need("New-AdminOnlyDirectory", [r"SetOwner\(\[Security\.Principal\.SecurityIdentifier\]'S-1-5-32-544'\)", r"SetAccessRuleProtection\(\$true, \$false\)", r"FileSystemAclExtensions\]::Create"], "created already protected")
    need("Assert-AdminOnlyDirectory", [r"Test-Gate 'backup-dir-secure'\)\) \{ return \}", r"Refuse 'backup-dir-secure' \"'\$Path' is a link\"", r"AreAccessRulesProtected", r"TrustedOwners -cnotcontains \$owner"], "protected folder check")
    need("Write-Backup", [r"New-AdminOnlyDirectory \$dir"], "the backup folder is created protected")
    need("Invoke-Apply", [r"Test-Gate 'empty-plan'\) -and \$pre\.Plan\.Count -eq 0\) \{ Refuse 'empty-plan'"], "an empty plan is a refusal")
    need("Write-ApplyResult", [r"not examined by this stage", r"read-back"], "closing lines are scoped to the stage")
    need("Find-RightsHits", [r"Test-Gate 'rights-by-name'"], "rights lookup by name")
    need("Get-ScanSids", [r"Test-Gate 'scan-all-sids'"], "scan of all Codex SIDs")
    need("Test-ScopeOnlySid", [r"-ceq \$Sid"], "whole-SID firewall scope")
    need("Invoke-Main", [r"\$DryRun -and \$modes\.Count\) \{[^}]*return 2 \}"], "-DryRun cannot be combined with another mode")
    # stage 1: the identity checks run in their own small functions, the helpers call them, and delete by SID / id only
    need("Assert-UserIdentity", [r"Test-Gate 'sid-match'\) \{ Refuse 'sid-match'"], "account SID match")
    need("Assert-NoProfile", [r"\$State\.profileListEntry -or \$State\.cimProfile -or @\(\$State\.profileFolders\)\.Count\) -and \(Test-Gate 'no-profile'\)\) \{\s*Refuse 'no-profile'"], "no profile of any kind")
    need("Assert-GroupIdentity", [r"Test-Gate 'sid-match'\) \{ Refuse 'sid-match'"], "group SID match")
    need("Assert-GroupMembers", [r"\$AllowedSids -cnotcontains \$_", r"Test-Gate 'group-members'\)\) \{ Refuse 'group-members'"], "group members")
    need("Assert-FirewallIdentity", [r"Test-Gate 'fw-identity'\) \{", r"\$l\.Count -ne 1\) \{ Refuse 'fw-identity'", r"\$l\[0\]\.Name -cne \$Entry\.Name\) \{ Refuse 'fw-identity'", r"Test-ScopeOnlySid \$LocalUser \$Entry\.UserSid\)\) \{ Refuse 'fw-identity'"], "rule identity")
    need("Assert-RegistryShape", [r"Test-Gate 'reg-value-shape'\) -and \('\{0\}:\{1\}' -f \$Kind, \$Value\) -cne 'DWord:0'\) \{\s*Refuse 'reg-value-shape'"], "registry value shape")
    need("Disable-AllowedUser", [r"Assert-SpecAllowed \$Spec", r"Assert-NoWildcard", r"Test-Gate 'name-allowlist'\) \{ Refuse 'name-allowlist'", r"Assert-UserIdentity \$e\[0\] \$live\.SID\.Value \$Name", r"Disable-LocalUser -SID \$sid"], "accounts are disabled by SID, from the allowlist only")
    need("Remove-AllowedUser", [r"Assert-SpecAllowed \$Spec", r"Assert-NoWildcard", r"\$e\.Count -ne 1\) \{\s*if \(Test-Gate 'name-allowlist'\) \{ Refuse 'name-allowlist'", r"Assert-UserIdentity \$e\[0\] \$live\.SID\.Value \$Name", r"Win32_UserProfile -ErrorAction Stop", r"Assert-NoProfile \$st \$Name", r"Remove-LocalUser -SID \$sid"], "an account is removed by its SID, from the allowlist only, with no profile")
    need("Remove-AllowedGroup", [r"Assert-SpecAllowed \$Spec", r"Assert-NoWildcard", r"Test-Gate 'name-allowlist'\) \{ Refuse 'name-allowlist'", r"Assert-GroupIdentity \$g \$live\.SID\.Value \$Name", r"Assert-GroupMembers @\(Get-GroupMemberSids \$Name\)", r"Remove-LocalGroup -SID \$sid"], "a group is removed by its SID, empty of foreign members")
    need("Remove-AllowedFirewallRule", [r"Assert-SpecAllowed \$Spec", r"Test-Gate 'name-allowlist'\) \{ Refuse 'name-allowlist'", r"Assert-NoWildcard", r"Get-NetFirewallRule -DisplayName \$DisplayName -ErrorAction Stop", r"Assert-FirewallIdentity \$e\[0\] \$live \$lu \$DisplayName", r"Remove-NetFirewallRule -Name \$id"], "a rule is removed by its id after identity checks")
    need("Remove-AllowedRegistryValue", [r"Assert-SpecAllowed \$Spec", r"Assert-NoWildcard", r"Test-Gate 'name-allowlist'\) \{ Refuse", r"Assert-RegistryShape", r"Remove-ItemProperty"], "a registry value is removed after its shape is checked")
    need("Invoke-Step", [r"'acl' \{ Remove-SidAcesTree", r"'firewall' \{ Remove-AllowedFirewallRule", r"'registry' \{ Remove-AllowedRegistryValue", r"'disable' \{ Disable-AllowedUser", r"'user' \{ Remove-AllowedUser", r"'group' \{ Remove-AllowedGroup"], "every step kind maps to its guarded helper")
    need("Get-Plan", [r"kind = 'disable'", r"kind = 'firewall'", r"kind = 'registry'", r"kind = 'user'", r"kind = 'group'"], "disable first, irreversible last")
    need("Get-StepAbsent", [r"'disable'", r"'firewall'", r"'registry'", r"'user'", r"'group'", r"default \{ return \$false \}"], "every step kind has an absence check, an unknown kind is never absent")
    need("Get-VerifyProblems", [r"Test-Gate 'empty-plan'\) -and @\(\$Plan \| Where-Object", r"if \(\$s\.present\) \{ \$p\.Add", r"foreach \(\$f in \$Findings\) \{ \$p\.Add", r"Get-CertificationProblems \$Scans"], "what a verify reports")
    need("Invoke-VerifyRun", [r"Get-VerifyProblems \$d\.Plan \$d\.Findings \$scans \$Stage"], "verify reports through the shared function")
    need("Get-ApplyVerdict", [r"\$Code -eq 0\) -and \(@\(\$Left\)\.Count -eq 0\) -and \(@\(\$Cert\)\.Count -eq 0\)"], "the verdict")
    need("Get-LinkNameRoots", [r"\$_\.Path", r"Test-Gate 'link-roots'\) \{ \$r \+= @\(\$Spec\.LinkRoots"], "other names of a hard-linked file may be under the allowlisted folders and the one pinned link folder only")
    need("Get-ExtraRuleNames", [r"\$_\.Name -ceq \$n"], "extra rules")
    need("Get-LiveState", [r"Get-ExtraRuleNames \$Spec"], "extra rules are listed")
    need("Test-WfpExportUsable", [r"<filters"], "export usable")
    need("Test-RightsExportUsable", [r"\[Privilege Rights\]"], "export usable")
    need("Get-HeavyState", [r"Test-WfpExportUsable \$txt", r"Test-RightsExportUsable \$txt", r"\$o\.checked = \(\$o\.notRun\.Count -eq 0\)"], "garbage exports are a check that did not run")
    need("Get-GroupMemberSids", [r"catch \{ return @\('unreadable'\) \}"], "an unreadable group is never empty")
    need("Get-UserState", [r"Get-UserGroupNames", r"StartsWith\(\$U\.Name"], "account groups and profile folders")
    need("Invoke-RestoreAcl", [r"Assert-Elevated \$IsAdmin", r"Test-Gate 'restore-real-blocked'\)\) \{ Refuse 'restore-real-blocked'", r"Assert-SpecAllowed \$Spec"], "restoring on the real machine is refused")
    entry = _entry_block(ps1)
    if _in_order(entry, [r"\btry\b", r"\bcatch\b", r"\bfinally\b", r"\$HoldOpen", r"Read-Host", r"exit \$code"]):
        out.append("the entry block does not hold the window open in a finally after an unhandled error")
    if not re.search(r"\[switch\]\$HoldOpen", ps1):
        out.append("no -HoldOpen switch")
    return out


def _mutate(fn: dict[str, str], name: str, old: str, new: str) -> dict[str, str]:
    body = fn[name]
    assert old in body, f"mutation target not found in {name}: {old}"
    fn2 = dict(fn)
    fn2[name] = body.replace(old, new, 1)
    return fn2


# ---------------------------------------------------------------- tests


def test_script_and_launcher_are_ascii() -> None:
    assert not non_ascii(_PS1.read_bytes())
    assert not non_ascii(_CMD.read_bytes())
    assert non_ascii("café".encode("utf-8"))


def test_no_function_is_named_like_a_builtin_alias() -> None:
    assert alias_collisions(_PS1.read_text(encoding="utf-8")) == []
    assert alias_collisions("function Rd { Remove-Item @args }\nfunction Get-Thing {}") == ["Rd"]


def test_launcher_copies_to_a_protected_folder_checks_the_hash_and_survives_a_cancelled_uac_prompt() -> None:
    cmd = _CMD.read_text(encoding="ascii")
    assert launcher_problems(cmd) == []
    stub = _stub_of(cmd)
    assert stub is not None
    # the embedded text is the reviewed stub file, comments left out
    ref = "\n".join(ln for ln in _STUB.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if not ln.lstrip().startswith("#"))
    assert stub == ref
    assert max(len(ln) for ln in cmd.splitlines()) < 8000
    for broken in (
        cmd.replace("-ErrorAction Stop", ""),
        cmd.replace("pause", "rem"),
        cmd + "\n-NoExit",
        cmd.replace("SHA256", "SHA1"),
        _with_stub(cmd, stub.replace("-HoldOpen", "")),
        _with_stub(cmd, stub.replace("-ExpectScriptSha256", "-Nope")),
        _with_stub(cmd, stub.replace("run-1743", "run")),
        _with_stub(cmd, stub.replace("-ne $want", "-eq $want")),
        _with_stub(cmd, stub.replace("SetAccessRuleProtection($true, $false)", "")),
        _with_stub(cmd, stub.replace("AreAccessRulesProtected", "Exists")),
    ):
        assert launcher_problems(broken) != []


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
def test_the_elevated_stub_parses() -> None:
    stub = _stub_of(_CMD.read_text(encoding="ascii"))
    code = "$e=$null;$t=$null;[void][Management.Automation.Language.Parser]::ParseInput([Console]::In.ReadToEnd(),[ref]$t,[ref]$e); if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 3 }"
    done = subprocess.run([_PWSH, "-NoProfile", "-Command", code], input=stub, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
def test_script_parses_and_its_apply_path_is_structurally_intact() -> None:
    ps1 = _PS1.read_text(encoding="utf-8")
    assert structural_problems(_load_functions(), ps1) == []


_PLANTED = [
        ("Invoke-Apply", "Assert-Elevated $IsAdmin", ""),
        ("Invoke-Apply", "if ($pre.Findings.Count) { Refuse 'unexpected-live'", "if ($false) { Refuse 'unexpected-live'"),
        ("Invoke-Apply", "$ExpectPlan -cne $pre.Digest) { Refuse 'plan-digest'", "$false) { Refuse 'plan-digest'"),
        ("Invoke-Apply", "if (Test-Gate 'plan-digest') {", "if ($false) {"),
        ("Invoke-Apply", "if ($cert.Count) {\n                $res.code = 1", "if ($false) {\n                $res.code = 1"),
        (
            "Invoke-Apply",
            "if ($res.code -eq 0) { & $runSteps @($pre.Plan | Where-Object { $_.kind -cne 'acl' }) }",
            "if ($true) { & $runSteps @($pre.Plan | Where-Object { $_.kind -cne 'acl' }) }",
        ),
        ("Invoke-Apply", "if ($hasAcl -and ($Spec.Mode -ceq 'real') -and (Test-Gate 'acl-stage-blocked'))", "if ($false)"),
        ("Invoke-Apply", "if ($hasAcl -and $res.code -eq 0 -and -not $script:SimulateOnly)", "if ($res.code -eq 0 -and -not $script:SimulateOnly)"),
        ("Write-Backup", "if (Test-StageHas $Stage 'Acl') { $script:LastSnapshot = Write-TreeSnapshot", "if ($true) { $script:LastSnapshot = Write-TreeSnapshot"),
        ("Get-LiveState", "$(if (Test-StageHas $Stage 'Acl') { @(", "$(if ($true) { @("),
        ("Assert-UserIdentity", "if ($Entry.Sid -and $LiveSid -cne $Entry.Sid) {", "if ($false) {"),
        ("Assert-NoProfile", "if (($State.profileListEntry -or $State.cimProfile -or @($State.profileFolders).Count) -and (Test-Gate 'no-profile')) {", "if ($false) {"),
        ("Assert-GroupIdentity", "if ($Group.Sid -and $LiveSid -cne $Group.Sid) {", "if ($false) {"),
        ("Assert-GroupMembers", "if ($foreign.Count -and (Test-Gate 'group-members')) {", "if ($false) {"),
        ("Assert-FirewallIdentity", "if ($Entry.UserSid -and -not (Test-ScopeOnlySid $LocalUser $Entry.UserSid)) {", "if ($false) {"),
        ("Assert-FirewallIdentity", "if ($Entry.Name -and $l[0].Name -cne $Entry.Name) {", "if ($false) {"),
        ("Assert-FirewallIdentity", "if ($l.Count -ne 1) {", "if ($false) {"),
        ("Assert-RegistryShape", "-cne 'DWord:0') {", "-ceq 'never') {"),
        ("Remove-AllowedUser", "Assert-NoProfile $st $Name", ""),
        ("Remove-AllowedUser", "Assert-UserIdentity $e[0] $live.SID.Value $Name", ""),
        ("Remove-AllowedUser", "Remove-LocalUser -SID $sid", "Remove-LocalUser -Name $Name"),
        ("Remove-AllowedUser", "if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' \"account", "if ($false) { Refuse 'name-allowlist' \"account"),
        ("Disable-AllowedUser", "Disable-LocalUser -SID $sid", "Disable-LocalUser -Name $Name"),
        ("Disable-AllowedUser", "Assert-UserIdentity $e[0] $live.SID.Value $Name", ""),
        ("Remove-AllowedGroup", "Assert-GroupMembers @(Get-GroupMemberSids $Name)", "$null = @(Get-GroupMemberSids $Name)"),
        ("Remove-AllowedGroup", "Assert-GroupIdentity $g $live.SID.Value $Name", ""),
        ("Remove-AllowedGroup", "Remove-LocalGroup -SID $sid", "Remove-LocalGroup -Name $Name"),
        ("Remove-AllowedGroup", "if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' \"group", "if ($false) { Refuse 'name-allowlist' \"group"),
        ("Remove-AllowedFirewallRule", "Assert-FirewallIdentity $e[0] $live $lu $DisplayName", ""),
        ("Remove-AllowedFirewallRule", "Remove-NetFirewallRule -Name $id", "Remove-NetFirewallRule -DisplayName $DisplayName"),
        ("Remove-AllowedFirewallRule", "if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' \"firewall", "if ($false) { Refuse 'name-allowlist' \"firewall"),
        ("Remove-AllowedRegistryValue", "Assert-RegistryShape ([string]$key.GetValueKind($Name)) $key.GetValue($Name) $Name", ""),
        ("Remove-AllowedRegistryValue", "if (Test-Gate 'name-allowlist') { Refuse 'name-allowlist' \"registry", "if ($false) { Refuse 'name-allowlist' \"registry"),
        ("Invoke-Apply", "if (-not $script:SimulateOnly -and -not (Get-StepAbsent $Spec $now $s)) { throw", "if ($false) { throw"),
        ("Invoke-Apply", "$res.ok = Get-ApplyVerdict $res.code $left $cert", "$res.ok = ($res.code -eq 0)"),
        ("Invoke-Step", "'disable' { Disable-AllowedUser $Spec $Step.target }", ""),
        ("Get-LiveState", "$extra = Get-ExtraRuleNames $Spec (Get-FirewallRulesByDisplayName \"$glob*\")", "$extra = @()"),
        ("Get-HeavyState", "if (-not (Test-WfpExportUsable $txt)) {", "if ($false) {"),
        ("Get-HeavyState", "if (-not (Test-RightsExportUsable $txt)) {", "if ($false) {"),
        ("Get-HeavyState", "$o.checked = ($o.notRun.Count -eq 0)", "$o.checked = $true"),
        ("Get-HeavyState", "catch { $o.notRun += \"scheduled tasks", "catch { $null = \"scheduled tasks"),
        ("Get-HeavyState", "catch { $o.notRun += \"services (could", "catch { $null = \"services (could"),
        ("Get-HeavyState", "if (-not $IsAdmin) { $o.notRun += 'Windows", "if (-not $IsAdmin) { $null = 'Windows"),
        ("Get-GroupMemberSids", "catch { return @('unreadable') }", "catch { return @() }"),
        ("Get-VerifyProblems", "if ($s.present) { $p.Add", "if ($false) { $p.Add"),
        ("Get-VerifyProblems", "foreach ($f in $Findings) { $p.Add($f) }", ""),
        ("Get-Findings", "if ($u.exists -and $u.lastLogon) {", "if ($false) {"),
        ("Get-Findings", "if ($u.profileListEntry) { $f.Add", "if ($false) { $f.Add"),
        ("Get-Findings", "if ($u.cimProfile) { $f.Add", "if ($false) { $f.Add"),
        ("Get-Findings", "foreach ($p in $u.profileFolders) { $f.Add", "foreach ($p in @()) { $f.Add"),
        ("Get-Findings", "if ($r.direction -ne 'Outbound' -or $r.action -ne 'Block') {", "if ($false) {"),
        ("Get-Findings", "if ($null -ne $v -and $v -cne 'DWord:0') {", "if ($false) {"),
        ("Get-Findings", "foreach ($e in $State.firewallExtra) { $f.Add", "foreach ($e in @()) { $f.Add"),
        ("Get-Findings", "foreach ($s in $h.services) { $f.Add", "foreach ($s in @()) { $f.Add"),
        ("Get-Findings", "foreach ($t in $h.tasks) { $f.Add", "foreach ($t in @()) { $f.Add"),
        ("Get-Findings", "foreach ($w in $h.wfpHits) { $f.Add", "foreach ($w in @()) { $f.Add"),
        ("Get-Findings", "foreach ($r in $h.rightsHits) { $f.Add", "foreach ($r in @()) { $f.Add"),
        ("Get-Findings", "if ($g.description -cne $Spec.Group.Description) {", "if ($false) {"),
        ("Get-Findings", "if ($g.sid -cne $g.expectedSid) {", "if ($false) {"),
        ("Get-Findings", "if ($r.name -cne $r.expectedName) {", "if ($false) {"),
        ("Get-Findings", "if (@('Users', $Spec.Group.Name) -inotcontains $gn) {", "if ($false) {"),
        ("Invoke-RestoreAcl", "if (($Spec.Mode -ceq 'real') -and (Test-Gate 'restore-real-blocked')) {", "if ($false) {"),
        ("Get-PlanDigest", "|$($_.present)|$($_.state)\"", "\""),
        ("Get-Plan", "present = $u.exists", "present = $false"),
        ("Get-Plan", "present = ($u.exists -and $u.enabled -ne $false)", "present = $false"),
        ('Get-AceDelta', '$o = @(ConvertTo-AceKeys $Old $DropSids)', 'return $null; $o = @(ConvertTo-AceKeys $Old $DropSids)'),
        ('Find-SidAcesDeep', "if ($dropRx -and ($dropRx.Replace($old, '') -ceq $s)) { $c.fast++ }", 'if ($true) { $c.fast++ }'),
        ('Find-SidAcesDeep', 'if ($d) { $collateral.Add("$plain  $d") }', 'if ($false) { $collateral.Add("$plain  $d") }'),
        ('Remove-ObjectSids', "if ((Test-Gate 'empty-after') -and -not (Test-SddlHasAces $new))", 'if ($false)'),
        ('ConvertTo-WritableSddl', "$head = $head.Replace('AI', 'ARAI')", '$head = $head'),
        ('Remove-SidsFromSddl', '    if (-not $Sids.Count) { return $Sddl }\n    $rx =', '    return $Sddl\n    $rx ='),
        ('Get-ScopeSids', "$Path.StartsWith($tp + '\\', ", '$Path.StartsWith($tp, '),
        ('Get-ExplicitPurgeSids', '$_.Sid -ceq $sid -and -not $_.Inherited', '$_.Sid -ceq $sid -and $false'),
        ('Find-SidAcesDeep', 'if (-not $emptyMemo[$s]) { $empty.Add($plain) }', 'if ($false) { $empty.Add($plain) }'),
        ('Get-IncompleteRuns', 'if (-not $done) { $out += $d.FullName }', 'if ($false) { $out += $d.FullName }'),
        ('Resolve-ResumeBaseline', "if ($inc.Count -and (Test-Gate 'resume-required')) {", 'if ($false) {'),
        ('Test-ScopeOnlySid', "return ($aces.Count -eq 1) -and ($aces[0].Type -ceq 'A') -and ($aces[0].Sid -ceq $Sid)", 'return ($aces.Count -ge 1) -and ($aces[0].Sid -ceq $Sid)'),
        ('Test-StageHas', '$st = "$Stage".ToLowerInvariant()', '$st = "$Stage"'),
        ('Get-PlanDigest', '"script=$(Get-ScriptSha256)"', '"script=x"'),
        ('Get-LocalUserOrNull', 'catch [Microsoft.PowerShell.Commands.UserNotFoundException] { return $null }', 'catch { return $null }'),
        ('Get-LocalGroupOrNull', 'catch [Microsoft.PowerShell.Commands.GroupNotFoundException] { return $null }', 'catch { return $null }'),
        ('Get-FirewallRulesByDisplayName', "-like '*No MSFT_NetFirewallRule objects found*') { return @() }\n        throw", "-like '*No MSFT_NetFirewallRule objects found*') { return @() }\n        return @()"),
        ("Get-LinkNameRoots", "if (Test-Gate 'link-roots') {", "if ($false) {"),
        ("Remove-SidAcesTree", "$roots = Get-LinkNameRoots $Spec", "$roots = @($Spec.AclTargets | ForEach-Object { $_.Path }) + @('C:\\')"),
        ("Remove-ObjectSids", "$nm.StartsWith($_.TrimEnd('\\') + '\\', [StringComparison]::OrdinalIgnoreCase)", "$nm.StartsWith($_.TrimEnd('\\'), [StringComparison]::OrdinalIgnoreCase)"),
        ("Assert-SpecAllowed", "-cne $script:RealSpecPin", "-cne $script:RealSpecPin -and $false"),
        ("Get-CertificationProblems", "$sc.foldersLeftUnscanned -gt 0 -or $sc.unreadable -gt 0", "$false"),
        ("Get-Findings", "if (-not $h.checked) {", "if ($false) {"),
        ("Write-TreeSnapshot", "if ($below.Count -and (Test-Gate 'codex-below-root')) {", "if ($false) {"),
        ("Write-TreeSnapshot", "if ($emptied.Count -and (Test-Gate 'empty-after')) {", "if ($false) {"),
        ("Write-TreeSnapshot", "if ($unreadN -and (Test-Gate 'snapshot-unreadable')) {", "if ($false) {"),
        ("Invoke-Apply", "if (Test-Gate 'collateral-stop') { $cert +=", "if ($false) { $cert +="),
        ("Invoke-Apply", "if ($hasAcl) { $resume = Resolve-ResumeBaseline", "if ($false) { $resume = Resolve-ResumeBaseline"),
        ("Remove-ObjectSids", "if (Test-Gate 'acl-handle') {", "if ($false) {"),
        ("Remove-ObjectSids", "if ($outside.Count) { return", "if ($false) { return"),
        ("Remove-ObjectSids", "if ($back -cne $new) { return", "if ($false) { return"),
        ("Remove-ObjectSids", "$write = ConvertTo-WritableSddl $new", "$write = $new + 'D:'"),
        ("Remove-SidAcesTree", "if ((Test-Gate 'acl-reparse') -and", "if ($false -and"),
        ("Invoke-RestoreAcl", "Assert-AdminOnlyDirectory $Dir", ""),
        ("Resolve-ResumeBaseline", "Refuse 'resume-target'", "Write-Host 'resume-target'"),
        ("Get-Findings", "foreach ($m in $g.memberSids) { if ($allowed -cnotcontains $m) {", "foreach ($m in $g.memberSids) { if ($false) {"),
        ("Get-Findings", "if ($u.exists -and $u.sid -cne $u.expectedSid) {", "if ($false) {"),
        ("Get-Findings", "if (-not (Test-ScopeOnlySid ([string]$r.localUser) $want)) {", "if ($false) {"),
        ("Get-Findings", "if ($r.count -gt 1) {", "if ($false) {"),
        ("Invoke-Main", "if (($Guided) -and (Test-StageHas $Stage 'Acl') -and (Test-Gate 'acl-stage-blocked'))", "if ($false)"),
        ("Invoke-Apply", "if ((Test-Gate 'empty-plan') -and $pre.Plan.Count -eq 0) {", "if ($false) {"),
        ("Get-UserState", "Get-LocalUserOrNull $U.Name", "Get-LocalUser -Name $U.Name -ErrorAction SilentlyContinue"),
        ("Get-GroupState", "Get-LocalGroupOrNull $g.Name", "Get-LocalGroup -Name $g.Name -ErrorAction SilentlyContinue"),
        ("Get-FirewallRuleState", "Get-FirewallRulesByDisplayName $F.DisplayName", "Get-NetFirewallRule -DisplayName $F.DisplayName -ErrorAction SilentlyContinue"),
        ("Get-HeavyState", "Get-Service -ErrorAction Stop", "Get-Service -ErrorAction SilentlyContinue"),
        ("Test-StageHas", "$st = \"$Stage\".ToLowerInvariant()", "$st = \"$Stage\""),
        ("Get-PlanDigest", "\"script=$(Get-ScriptSha256)\"", "\"script=x\""),
        ("Write-Backup", "New-AdminOnlyDirectory $dir", "New-Item -ItemType Directory -Path $dir -Force | Out-Null"),
        ("Assert-AdminOnlyDirectory", "if (-not $acl.AreAccessRulesProtected) {", "if ($false) {"),
        ("Invoke-Main", "if ($DryRun -and $modes.Count)", "if ($false)"),
]

_PLANTED_VERDICT: dict[int, str] = {}


def _planted_verdicts() -> dict[int, str]:
    """For every planted single-line disablement: which lock noticed it ('structural', 'behavioural' or 'SURVIVED'). Computed once, behavioural runs in parallel."""
    if _PLANTED_VERDICT:
        return _PLANTED_VERDICT
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    ps1 = _PS1.read_text(encoding="utf-8")
    fn = _load_functions()
    work = Path(tempfile.mkdtemp(prefix="rcs-planted-"))
    pending: list[tuple[int, Path]] = []
    for i, (name, old, new) in enumerate(_PLANTED):
        if structural_problems(_mutate(fn, name, old, new), ps1):
            _PLANTED_VERDICT[i] = "structural"
            continue
        body = fn[name]
        assert ps1.count(body) == 1, f"function body of {name} must occur once"
        broken = work / f"broken{i}.ps1"
        broken.write_text(ps1.replace(body, body.replace(old, new, 1), 1), encoding="utf-8")
        pending.append((i, broken))

    def run(item: tuple[int, Path]) -> tuple[int, str]:
        i, path = item
        results = run_cheap_checks(path, broken=True)
        return i, ("behavioural" if any(not r["pass"] for r in results) else "SURVIVED")

    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, verdict in pool.map(run, pending):
            _PLANTED_VERDICT[i] = verdict
    shutil.rmtree(work, ignore_errors=True)
    return _PLANTED_VERDICT


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
@pytest.mark.parametrize("idx", range(len(_PLANTED)), ids=[f"{n}:{o[:40]}" for n, o, _ in _PLANTED])
def test_each_planted_violation_is_caught_by_the_structural_or_the_behavioural_lock(idx: int) -> None:
    """Each single-line disablement of a safety must be caught by the structural lock or, failing that, by a behavioural check."""
    name, old, _new = _PLANTED[idx]
    assert _planted_verdicts()[idx] != "SURVIVED", f"neither lock noticed: {name}: {old}"


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
def test_structural_check_rejects_a_spec_pin_deletion_and_a_naked_entry_block() -> None:
    ps1 = _PS1.read_text(encoding="utf-8")
    fn = _load_functions()
    assert structural_problems(fn, re.sub(r"\$script:RealSpecPin = '[0-9a-f]{64}'", "$script:RealSpecPin = ''", ps1)) != []
    naked = ps1.split("if ($MyInvocation.InvocationName -ne '.')", 1)[0] + "if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-Main) }"
    assert structural_problems(fn, naked) != []


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
def test_dryrun_with_another_mode_is_refused_and_holdopen_still_holds() -> None:
    """Two refused invocations only: no real state is read or changed."""
    done = subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(_PS1), "-DryRun", "-Apply", "-HoldOpen"],
        input="\n", capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 2, done.stdout + done.stderr
    assert "cannot be combined" in done.stdout
    assert "Exit code 2" in done.stdout
    done2 = subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(_PS1), "-Verify", "-Apply", "-HoldOpen"],
        input="\n", capture_output=True, text=True, timeout=120,
    )
    assert done2.returncode == 2 and "Choose one mode" in done2.stdout and "Exit code 2" in done2.stdout


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
def test_a_changed_script_is_refused_by_the_hash_the_launcher_passed() -> None:
    """The elevated copy compares its own file with the hash read before approval (refused invocations only)."""
    good = hashlib.sha256(_PS1.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()
    bad = subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(_PS1), "-ExpectScriptSha256", "0" * 64, "-Verify", "-Apply"],
        input="\n", capture_output=True, text=True, timeout=120,
    )
    assert bad.returncode == 2 and "is not the one the launcher computed" in bad.stdout
    ok = subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(_PS1), "-ExpectScriptSha256", good, "-Verify", "-Apply"],
        input="\n", capture_output=True, text=True, timeout=120,
    )
    assert ok.returncode == 2 and "Choose one mode" in ok.stdout and "launcher computed" not in ok.stdout


_CHEAP = _ROOT / "tests" / "security" / "remove_codex_sandbox_cheap_checks.ps1"


def run_cheap_checks(script: Path, broken: bool = False) -> list[dict]:
    """Runs the cheap checks against a script. For a deliberately broken copy a crash counts as a failed check."""
    done = subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(_CHEAP), "-ScriptPath", str(script)], capture_output=True, text=True, timeout=600
    )
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("[{")]
    if done.returncode != 0 or not lines:
        if broken:
            return [{"name": "the checks could not run on the broken copy", "pass": False, "err": done.stderr[-500:]}]
        raise AssertionError(done.stdout[-2000:] + done.stderr[-2000:])
    return json.loads(lines[-1])


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
def test_cheap_behavioural_checks_of_the_safety_logic_pass() -> None:
    """Pure helpers plus one tiny throwaway tree: the object's own list is edited, nothing else (runs without elevation)."""
    results = run_cheap_checks(_PS1)
    failed = [r for r in results if not r["pass"]]
    assert not failed, failed
    assert len(results) >= 30


# Each broken copy of the script must make at least one cheap check fail: the checks can fail, so a pass means something.


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
def test_a_mistyped_stage_exits_2_and_changes_nothing() -> None:
    done = subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(_PS1), "-Stage", "accountz", "-HoldOpen"],
        input="\n", capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 2, done.stdout + done.stderr
    assert "unknown -Stage" in done.stdout and "Nothing was changed" in done.stdout


@pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 not installed")
@pytest.mark.parametrize("stage", ["aclentries", "ALL", "AclEntries", "all"])
def test_guided_stage_two_is_refused_on_the_real_machine_in_any_letter_case(stage: str) -> None:
    """Refused before any state is read for a plan; nothing is applied (the window is held and closed with Enter)."""
    done = subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(_PS1), "-Guided", "-Stage", stage, "-HoldOpen"],
        input="\n", capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 2, done.stdout + done.stderr
    assert "not enabled for the real machine" in done.stdout


@pytest.mark.slow
@pytest.mark.skipif(
    _PWSH is None or os.environ.get("BLARAI_OPERATOR_SELFTEST") != "1",
    reason="opt-in: elevated shell and BLARAI_OPERATOR_SELFTEST=1",
)
def test_behavioural_selftest_passes_on_this_host() -> None:
    """The script's own throwaway-object self-test (not in the standing gate; run before the operator uses the script)."""
    done = subprocess.run([_PWSH, "-NoProfile", "-File", str(_PS1), "-SelfTest"], capture_output=True, text=True, timeout=1800)
    assert done.returncode == 0, done.stdout[-4000:]
    assert " 0 failed." in done.stdout
