# ws0 findings: primer vs Microsoft docs, and bypass record (ticket #1740)
Method: Microsoft Learn pages read as their MicrosoftDocs GitHub markdown source (raw.githubusercontent.com/MicrosoftDocs/{win32,sdk-api}), which is the page source of learn.microsoft.com. Local copies in ./ms/. "READ" = full text of the page read; "SUMMARY ONLY" = not read from a primary.

## TASK 1 evidence (appended as read)

### E1 Access-check order - READ
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/how-dacls-control-access-to-an-object
Quote: "The system examines each ACE in sequence until one of the following events occurs: An access-denied ACE explicitly denies any of the requested access rights to one of the trustees listed in the thread's access token. One or more access-allowed ACEs for trustees listed in the thread's access token explicitly grant all the requested access rights. All ACEs have been checked and there is still at least one requested access right that has not been explicitly allowed, in which case, access is implicitly denied."
Quote: "Because the system stops checking ACEs when the requested access is explicitly granted or denied, the order of ACEs in a DACL is important. Note that if the ACE order were different in the example, the system might have granted access to Thread A."
=> Deny does not beat allow by rule; it wins by ORDER. First match wins.

### E2 Canonical ACE order - READ
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/order-of-aces-in-a-dacl
Quote: "1. All explicit ACEs are placed in a group before any inherited ACEs. 2. Within the group of explicit ACEs, access-denied ACEs are placed before access-allowed ACEs. 3. Inherited ACEs are placed in the order in which they are inherited... 4. For each level of inherited ACEs, access-denied ACEs are placed before access-allowed ACEs."
Quote: "Functions such as AddAccessAllowedAceEx and AddAccessAllowedObjectAce add an ACE to the end of an ACL. It is the caller's responsibility to ensure that the ACEs are added in the proper order."
Quote: "the Windows XP operating system defines a preferred order for ACEs... The preferred order provides a simple framework that ensures that an access-denied ACE actually denies access."
=> An EXPLICIT allow on a folder sits before an INHERITED deny and wins. A deny appended by a raw API call can land after an allow and lose. Canonical order is a convention callers maintain, not an engine guarantee.

### E3 Inheritance - READ
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance
Quote: "an object's ACL can contain ACEs that it inherited from its parent container... a file in an NTFS file system can inherit ACEs from the directory that contains it."
Quote: "The ability to prevent a DACL or SACL from inheriting ACEs by setting the SE_DACL_PROTECTED or SE_SACL_PROTECTED bits in the security descriptor's control bits".

### E4 Access token contents; child inheritance - READ
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/access-tokens
Quote: "Access tokens contain: the SID for the user's account; SIDs for the groups of which the user is a member; a logon SID...; a list of the privileges held by either the user or the user's groups; ... An optional list of restricting SIDs".
Quote: "Every process executed on behalf of this user has a copy of this access token."
URL: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessa
Quote: "The new process runs in the security context of the calling process."
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-for-legacy-applications-
Quote: "When an unpackaged process running in an app container calls CreateProcess, the child process typically inherits the parent's token. That token includes the integrity level (IL) and app container info."
=> Child inherits parent token by default: CONFIRMED. Not an invariant: CreateProcessAsUser / CreateProcessWithLogon can give a child a different token if the caller holds the privileges.

### E5 Restricted tokens - READ (two pages)
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens
Quote: "The CreateRestrictedToken function can restrict a token in the following ways: Remove privileges from the token. Apply the deny-only attribute to SIDs in the token so that they cannot be used to access secured objects. Specify a list of restricting SIDs, which can limit access to securable objects."
Quote: "When a restricted process or thread tries to access a securable object, the system performs two access checks: one using the token's enabled SIDs, and another using the list of restricting SIDs. Access is granted only if both access checks allow the requested access rights."
Quote: "Applications that use restricted tokens should run the restricted application on desktops other than the default desktop. This is necessary to prevent an attack by a restricted application, using SendMessage or PostMessage, to unrestricted applications on the default desktop."
URL: https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken
Quote (WRITE_RESTRICTED 0x8): "The new token contains restricting SIDs that are considered only when evaluating write access."
Quote (deny-only): "Disabling a SID turns on SE_GROUP_USE_FOR_DENY_ONLY and turns off SE_GROUP_ENABLED and SE_GROUP_ENABLED_BY_DEFAULT." / "The absence of a deny-only SID does not allow access."
Quote (restricting SIDs): "Restricting SIDs are always enabled for access checks." / "If the existing token is a restricted token, the list of restricting SIDs for the new token is the intersection of this array and the list of restricting SIDs for the existing token."
Quote (DISABLE_MAX_PRIVILEGE): "Disables all privileges in the new token except the SeChangeNotifyPrivilege privilege."
Quote (no elevation): "If a process calls CreateProcessAsUser using a restricted version of its own token, the calling process does not need to have the SE_ASSIGNPRIMARYTOKEN_NAME privilege." Restricted-tokens page: "This enables ordinary applications to create restricted processes."
Sandbox flag: SANDBOX_INERT "the system does not check AppLocker rules or apply Software Restriction Policies".

### E6 CreateAppContainerProfile - READ
URL: https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile
Quote: "Creates a per-user, per-app profile for an AppContainer." (min client Windows 8)
Quote: "The function creates a profile for the current user. To create a profile on behalf of another user, you must impersonate that user. To create profiles for multiple users of the same app, you must call CreateAppContainerProfile for each user."
Quote: "A profile contains folders and registry storage that are per-user and per-app. The folders have ACLs that prevent them from being accessed by other users and apps."
Returns: E_ACCESSDENIED "The caller doesn't have permission to create the profile."; ERROR_ALREADY_EXISTS "The application data store already exists."
Name rule: up to 64 chars, pattern "[-_. A-Za-z0-9]+".
=> The page does NOT state that administrator rights are required; it states the profile is per-user. NOT IN DOCS: an elevation requirement. The page is silent on elevation, so "needs admin" is neither confirmed nor refuted by docs; test on this box (one command).
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer ("Launch an AppContainer")
Quote: "Create the AppContainer by calling CreateAppContainerProfile... for an existing AppContainer it is necessary to derive the package SID from the moniker using the DeriveAppContainerSidFromAppContainerName API." Sample handles ERROR_ALREADY_EXISTS => the profile PERSISTS between launches (created once per user per name, deleted with DeleteAppContainerProfile). Primer's "no setup per launch" is right in effect; "can be made per launch" is possible only if the profile is created and deleted each time.
Quote: "Both the TMP and TEMP environment variables are also rerouted to a directory accessible to the AppContainer under the profile location: LOCALAPPDATA=C:\Users\TestUser\AppData\Local\Packages\TestAppContainer\AC; TEMP=...\AC\Temp".

### E7 AppContainer model (dual check, ALL APPLICATION PACKAGES, LPAC, IL) - READ
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer
Quote: "AppContainer SIDs (Package and Capability SIDs) are separate from the traditional user and group SIDs with both portions of the token being required to grant access to a protected resource via the object's discretionary access control list (DACL). This dual-principal model ensures that access to sensitive resources is tightly controlled... Furthermore, the permitted access is the intersection of that granted by the user/group SIDs and AppContainer SIDs".
Quote: "AppContainers run with a Low Integrity Level (IL)... if a resource has a mandatory label of Medium IL or lower and the DACL grants access through to the AppContainer (through a Package SID or Capability SID) then the AppContainer can read, write, or execute depending on the access granted to both principals in the DACL."
Quote: "Regular AppContainers are granted access to certain system files/directories, common registry keys and COM objects, however, LPAC needs specific capabilities to access resources that regular AppContainers can access."
Quote: "Less Privileged AppContainers (LPAC) are even more isolated than regular AppContainers and require further capabilities to gain access to resources that regular AppContainers already have access to such as the registry, files, and others. For example, LPAC cannot open any keys in the registry unless it has the registryRead capability and cannot use COM unless it has the lpacCom capability."
Quote: "without the network capability, an AppContainer cannot access the network".
LPAC launch: PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY = PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT ("which is specified by opting out of All Application Packages").
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-for-legacy-applications-
Quote: "An AppContainer is implemented by adding new information to the process token, changing SeAccessCheck() so that all legacy, unmodified access control list (ACL) objects block access requests from AppContainer processes by default, and re-ACL objects that should be available to AppContainers."
Quote: "being or not being in an app container is a second and orthogonal property. That said, if you are in an app container, then the integrity level (IL) is always low."
Quote: "They're isolated using file system and registry virtualization."
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation
Quote: "Even if vulnerability in an app is exploited, the app cannot access resources beyond what is granted to the AppContainer. Malicious apps cannot take over the rest of the machine." (marketing-grade; no kernel-exploit caveat on the page)
Quote: "Read-only access is less restricted." (File isolation section: "Read-write access can be granted to specific persistent files and registry keys. Read-only access is less restricted.")
Quote: "Process isolation: Sandboxing the application kernel objects..."; "Window isolation".
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/app-container-sid-constants : SECURITY_BUILTIN_PACKAGE_ANY_PACKAGE (0x00000001L) under SECURITY_APP_PACKAGE_AUTHORITY, i.e. the ALL APPLICATION PACKAGES SID S-1-15-2-1.
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/capability-sid-constants : SECURITY_CAPABILITY_INTERNET_CLIENT (0x1) "An account has access to the Internet from a client computer."; INTERNET_CLIENT_SERVER (0x2) "...from the client and server computers."; PRIVATE_NETWORK_CLIENT_SERVER (0x3) "An account has access to the Internet from a private network."
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control
Quote: "a principal with a low integrity level cannot write to an object with a medium integrity level, even if that object's DACL allows write access to the principal." / "Objects that lack an integrity label are treated as medium by the operating system; this prevents low-integrity code from modifying unlabeled objects."

### E8 Loopback and network capabilities - READ (previous-versions pages, Windows 8 era)
URL: https://learn.microsoft.com/en-us/previous-versions/windows/apps/hh780593(v=win.10) ("How to enable loopback and troubleshoot network isolation")
Quote: "Network communications using an IP loopback address cannot be used for interprocess communication (between two different apps) in a Windows Runtime app since this is restricted by network isolation."
Quote: "Loopback is permitted only for development purposes. Usage by a Windows Runtime app installed outside of Visual Studio is not permitted. Further, a Windows Runtime app can use an IP loopback only as the target address for a client network request. So a Windows Runtime app that uses a DatagramSocket or StreamSocketListener to listen on an IP loopback address is prevented from receiving any incoming packets."
Quote: "To enable access to loopback addresses, a developer must configure network isolation to exempt the app from loopback restrictions."  Command: "CheckNetIsolation.exe LoopbackExempt -a -p=S-1-15-2-..." (by package SID) or "-n=<AppContainer name>"; "-d" removes; "-c" removes all.
Elevation: the page says "A CMD window must then be opened with elevated privileges (run as Administrator)" ONLY for the Debug option. For LoopbackExempt -a it says nothing about elevation. => NOT IN DOCS whether the exemption needs admin. Not tested here.
URL: https://learn.microsoft.com/en-us/windows/win32/api/networkisolation/nf-networkisolation-networkisolationsetappcontainerconfig
Quote: "The security identifiers (SIDs) of app containers that are allowed to send loopback traffic. Used for debugging purposes." (No mention of privilege.)
URL: https://learn.microsoft.com/en-us/previous-versions/windows/apps/hh770532(v=win.10) ("How to set network capabilities")
Quote: "Certain capabilities that relate to networking must be enabled in the app manifest for the app to be granted network access. These capabilities are defined as security identifiers (SIDs)". internetClient "Provides outbound access to the Internet and networks in public places"; internetClientServer "inbound and outbound network access from the Internet..."; privateNetworkClientServer "inbound and outbound network access at the user's trusted places, like home and work."
=> Primer says "Connections to localhost are also blocked unless a special exemption is set": CONFIRMED (Win8-era page; the loopback restriction is the documented default). Primer says network is "a permission": CONFIRMED. Primer's wording "internetClient/privateNetworkClientServer" is not in the primer; the project-relevant fact: internetClient and privateNetworkClientServer do NOT cover loopback; loopback is a separate exemption per package SID. Old page says the exemption is a developer/debug facility ("for development purposes"). Policy risk: the docs frame it as unsupported for production; the mechanism still exists on current Windows (sdk-api page unchanged, still published).

### E9 WFP conditions - READ
URL: https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-condition-identifiers-
Quote: "FWPM_CONDITION_ALE_PACKAGE_ID: The security identifier (SID) of an app container. Data type: FWP_SID".
Quote: "FWPM_CONDITION_ALE_USER_ID: The identification of the local user. Data type: FWP_SECURITY_DESCRIPTOR_TYPE".
URL: https://learn.microsoft.com/en-us/windows/win32/fwp/permitting-and-blocking-applications-and-users (code comment)
Quote: "When evaluating SECURITY_DESCRIPTOR conditions, the filter engine checks for FWP_ACTRL_MATCH_FILTER access. If the DACL grants access, it does not mean that the traffic is allowed; it just means that the condition evaluates to true. Likewise if it denies access, the condition evaluates to false."
URL: https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-condition-flags-
Flags exist: FWP_CONDITION_FLAG_IS_LOOPBACK, FWP_CONDITION_FLAG_IS_APPCONTAINER_LOOPBACK ("Tests if the network traffic is app container loopback traffic"), FWP_CONDITION_FLAG_IS_NON_APPCONTAINER_LOOPBACK.
=> (d): WFP CAN filter on the AppContainer package SID (ALE_PACKAGE_ID, FWP_SID) - CONFIRMED, so the primer's "whether the network block can target it is an open question" is answerable: the documented condition exists. Whether ALE_USER_ID matches on a RESTRICTING SID is NOT IN DOCS: the user-id condition is an access check of the token against a security descriptor ("checks for FWP_ACTRL_MATCH_FILTER access"). A DACL naming the user's SID would match the restricted process too (the user SID is still in the token, and, if restricting SIDs are present, the doc'd two-pass check says both passes must allow; whether WFP's SD match applies the restricting-SID pass is not stated). So primer's "a network rule aimed at this identity would hit you too" is PLAUSIBLE but NOT IN DOCS; the doc'd mechanism is "rule matches by access check", and matching only the restricted token needs a deny-only/restricting-SID construction that the docs do not describe for WFP. Mark IMPRECISE/UNPROVEN; settle with a 10-line test (add a block filter whose SD names a distinct restricting SID and see).

### E10 Microsoft Security Servicing Criteria for Windows - READ (live page, fetched 2026-10-10)
URL: https://www.microsoft.com/en-us/msrc/windows-security-servicing-criteria  (MSRC page, not learn.microsoft.com; last revision line: "May 20, 2026: Added Keys and Credentials security in the Security Features section")
Table "Security boundaries" (all "Intent is to service? Yes / Bounty? Yes"):
- Network boundary: "An unauthorized network endpoint cannot access or tamper with the code and data on a customer's device."
- Kernel boundary: "A non-administrative user mode process cannot access or tamper with kernel code and data... For the NT kernel only, Administrator-to-kernel is not a security boundary."
- Process boundary: "An unauthorized user mode process cannot access or tamper with the code and data of another process."
- AppContainer sandbox boundary: "An AppContainer-based sandbox process cannot access or tamper with code and data outside of the sandbox based on the container capabilities"
- User boundary: "A user cannot access or tamper with the code and data of another user without being authorized."
- Session boundary: "A user logon session cannot access or tamper with another user logon session without being authorized."
- Web browser boundary; Virtual machine boundary ("includes Hyper-V Isolated Containers"); VSM boundary; VBS boundary.
Security FEATURES serviced ("Yes/Yes"): "Windows Resource Access Control: An identity (user, group) cannot access or tamper with a resource (file, named pipe, etc.) unless explicitly authorized to do so." Also BitLocker, Secure Boot, WDAC, Credential Guard, etc.
Non-boundaries (explicit): Windows Server Containers (shared kernel, "not intended to be used in hostile multitenancy"), Administrator to Kernel, Hyper-V Administrators Group. Quote: "*Note: The following list is non-exhaustive and is intended to address components commonly mistaken as boundaries. By default, components are not considered boundaries unless explicitly named as such."
Defense-in-depth features, "Intent is to service? No": User Account Control (UAC) "Prevent unwanted system-wide changes (files, registry, etc) without administrator consent"; AppLocker; Controlled Folder Access; MOTW; DEP/ASLR/KASLR/ACG/CIG/CFG. Quote: "Any vulnerability or bypass that affects these security features will not be serviced by default".
NOT NAMED anywhere on the page: restricted tokens (CreateRestrictedToken), low integrity level / Mandatory Integrity Control, WRITE_RESTRICTED, "standard user to administrator" as a row. By the page's own rule ("not considered boundaries unless explicitly named") restricted tokens and Low IL are NOT serviced boundaries; the closest named items are User boundary (user A vs user B) and AppContainer sandbox boundary. UAC (admin consent) is explicitly not serviced; a standard-user-to-admin EoP is serviced only via the Kernel boundary / Process boundary / Windows Resource Access Control rows (an EoP bug will normally be rated on those), but "standard user -> administrator" is not a row of its own: [DERIVED, not stated by the page].

### E11 Direct check on this box (icacls, read-only, non-elevated, 2026-10-10)
`icacls C:\Windows`, `C:\Program Files`, `C:\Windows\System32` each show:
  BUILTIN\Users:(RX) and (OI)(CI)(IO)(GR,GE)
  APPLICATION PACKAGE AUTHORITY\ALL APPLICATION PACKAGES:(RX) and (OI)(CI)(IO)(GR,GE)
  APPLICATION PACKAGE AUTHORITY\ALL RESTRICTED APPLICATION PACKAGES:(RX) and (OI)(CI)(IO)(GR,GE)
`icacls C:\Users`: Everyone:(RX) inherited-only entries.  `icacls C:\ProgramData`: BUILTIN\Users:(OI)(CI)(RX) and BUILTIN\Users:(CI)(WD,AD,WEA,WA) (Users can create files/folders: write-data on directories).  `icacls C:\`: NT AUTHORITY\Authenticated Users:(OI)(CI)(IO)(M) and Authenticated Users:(AD) (the #1686 class: any new top-level folder under C:\ inherits Modify for every signed-in account).
=> Claim (b) "does not admit it unless the folder names the container": WRONG as a general statement. A folder that grants ALL APPLICATION PACKAGES (S-1-15-2-1; SDDL alias "AC", SECURITY_BUILTIN_PACKAGE_ANY_PACKAGE) admits every AppContainer, and C:\Windows, C:\Program Files and System32 do on this machine; ALL RESTRICTED APPLICATION PACKAGES (S-1-15-2-2) is also granted there, which admits even LPAC. The primer's example ("all signed-in users" grant) is right: Users / Authenticated Users alone do not admit an AppContainer (dual check; the AC SID must also be granted). Microsoft doc: "Regular AppContainers are granted access to certain system files/directories, common registry keys and COM objects, however, LPAC needs specific capabilities". 

### E12 Private object namespace - READ
URL: https://learn.microsoft.com/en-us/windows/win32/api/securityappcontainer/nf-securityappcontainer-getappcontainernamedobjectpath
Quote: "The GetAppContainerNamedObjectPath function retrieves the named object path for the app container. Each app container has its own named object path."
URL (P0, secondary to MS): https://projectzero.google/2016/01/raising-dead.html  Quote: "Microsoft decided to add a transparent workaround. They did this by adding a new directory, AppContainerNamedObjects to the per-session directory... The directories have their DACL set so only the specific LowBox token can access them."
Registry: the "legacy apps" page says an AppContainer app "writes to its own virtual registry and application data folder"; LPAC "cannot open any keys in the registry unless it has the registryRead capability" (E7). A regular AppContainer does have read access to "common registry keys" (E7).

## TASK 2 - documented limitations and published bypasses

### B1 AppContainer network isolation bypass (WFP configuration) - READ (primary: Project Zero)
URL: https://projectzero.google/2021/08/understanding-network-access-windows-app.html  (James Forshaw, 2021-Aug-19)
Quote: "I recently discovered a configuration issue with the Windows Firewall which allowed the restrictions to be bypassed and allowed an AppContainer process to access the network. Unfortunately Microsoft decided it didn't meet the bar for a security bulletin so it's marked as WontFix." (P0 issue 2207: a Permit filter in the MICROSOFT_DEFENDER_SUBLAYER_WSH sublayer evaluated before "Block Outbound Default Rule" can avoid the capability requirement.)
Quote: "A normal application could abuse this configuration to run a network service without needing the administrator access normally required to grant the executable access. All you'd need to do is create an arbitrary AppContainer process in the permitted package and grant it the internetClientServer and/or the privateNetworkClientServer capabilities."
Quote: "the firewall is configured to treat all network addresses in the same context, granting the internetClient capability access to any address including your local 'private' network. This might be unexpected. In fact if you enumerate all the filters on the machine you won't find any filter to match the privateNetworkClientServer capability and using the capability will not grant access to any network" (as observed on his machine in 2021; check current behaviour before relying on it).
Quote (the mechanism is WFP on package SID and capability): "it will only match if the socket creator is in an AppContainer based on the FWPM_CONDITION_ALE_PACKAGE_ID condition. The FWPM_CONDITION_ALE_USER_ID also ensures that it will only match if the creator has the internetCapability capability which is S-1-15-3-1".
Quote (loopback): "it's not based on an IP address such as 127.0.0.1. Instead it's using a condition which checks for the IsLoopback condition flag... Even if you access the public IP addresses for th[e machine]..." ; "blocked loopback sockets timeout rather than fail immediately"; "the IsAppContainerLoopback flag... is only set if the two AppContainers have the same package SID."
Quote (the exemption needs admin): "loopback access was so beyond the pale for the designers that instead you can only grant access for debug purposes through an administrator only API."  (Add-AppModelLoopbackException in his module; same registration as CheckNetIsolation LoopbackExempt.) => Primer's "special exemption is set" is right and the exemption IS administrator-only per this source (P0); Microsoft's own pages are silent on elevation.
Quote (undocumented trick): the exemption's filter matches on "PACKAGE CAPABILITY\LOOPBACK", i.e. the package SID re-expressed as a capability SID; "Unfortunately it's not officially documented so can't be relied upon."
Also: "The basics of accessing the network from an AppContainer sandbox is documented by Microsoft... without the network capability, an AppContainer cannot access the network."

### B2 AppContainer sandbox escape via weak broker ACLs (access check combination) - READ (primary: Project Zero)
URL: https://googleprojectzero.blogspot.com/2014/12/internet-explorer-epm-sandbox-escape.html  (2014-Dec-01, CVE-2014-6350, MS14-065, three IE Enhanced Protected Mode escapes)
Quote: "The vulnerability was due to weak permissions on the broker process when IE is running in EPM mode."
Quote: "The access check used for code running in an AppContainer is slightly more complicated than the normal Windows one. Instead of a single access check there are two separate checks... The bitwise AND between the two sets of permissions is the maximum grantable permissions". Result: sandboxed process could OpenProcess(PROCESS_VM_READ) on the broker, then used DCOM marshalling to get code execution in the broker.
Class: brokers and same-user processes whose DACL grants a capability SID or ALL APPLICATION PACKAGES more than intended. The AppContainer boundary is only as good as every object the same user owns (processes, sections, pipes, COM servers).

### B3 Restricted-token weakness in the kernel - READ (primary: Project Zero)
URL: https://projectzero.google/2020/04/you-wont-believe-what-this-one-line.html  (2020-Apr-21, CVE-2020-0981, fixed April 2020; bug introduced in Windows 10 1903)
Quote: "The Chromium sandbox on Windows ... the main [weakness] being the sandbox's implementation is reliant on the security of the Windows OS... If a bug is found in the security enforcement mechanisms of Windows then the sandbox can break."
Quote: "A Restricted Token... Permanently disabling Groups. Removing Privileges. Adding Restricted SIDs." and "Any process on Windows can create a new process with a different Token, for example by calling CreateProcessAsUser. What stops a sandboxed process creating a new process using an unrestricted token?" Answer given: kernel SeIsTokenAssignableToProcess (token must be a child or sibling of the current token; restricted tokens are forced to be child via "NewToken -> ParentTokenId = OldToken -> TokenId"), plus Chromium's Job object (process quota 1) and the child-process mitigation policy. The bug broke the restricted-token parent/sibling assumption.
Quote: "The exploitation process is also an interesting insight into the little weaknesses in Windows which in themselves do not cross a security boundary but led to a successful sandbox escape."
URL: https://googleprojectzero.blogspot.com/2020/06/ff-sandbox-escape-cve-2020-12388.html  (2020-Jun-17)
Quote: "with L5, one content process can open another for full access... down to the Default DACL of the Primary Token of the process." (Class: processes sharing a restricted token can open each other through the token's default DACL; fix = random per-sandbox SID added to restricting SIDs and the default DACL.)

### B4 Restricted token / low IL limits - READ (Chromium design doc, a primary for Chromium, secondary for Windows)
URL: https://raw.githubusercontent.com/chromium/chromium/main/docs/design/sandbox.md (docs/design/sandbox.md)
Quote (assumptions): "All the securable resources have a better than null security descriptor. In other words, there are no critical resources with misconfigured security. The computer is not already compromised by malware. Third party software does not weaken the security of the system."
Quote: "By design, the sandbox token cannot protect the non-securable resources such as: Mounted FAT or FAT32 volumes... TCP/IP: The security of TCP/IP sockets in Windows 2000 and Windows XP (but not in Vista) is effectively null... Some unlabelled objects, such as anonymous shared memory sections".
Quote (low IL): "A low integrity level token can access only the following shared resources: Read access to most files; Write access to %USER PROFILE%\AppData\LocalLow; Read access to most of the registry; ... TCP/IP Sockets; ... COM interfaces with LI launch activation rights; Named pipes exposed via LI labels".
Quote: "By default, a token can read an object of a higher integrity level, but not write to it."
Quote: "The token and the job object define a security boundary: that is, all processes with the same token and in the same job object are effectively in the same security context. ... The sandbox creates a third desktop" (window-message attack class; same as Microsoft's own warning in E5).
Quote (Chromium's own LowBox use): "network checks are enforced if the token is a Low Box token and the INTERNET_CLIENT Capability is not present. The sandbox therefore takes the existing restricted token and adds the Low Box attributes, without granting any Capabilities, so as to gain the additional protection of no network access".
=> Restricted token + low IL alone: reads are mostly open, TCP/IP not gated. Primer's "stricter form can confine writes" is right and "confine reads" requires the full Chromium-style restricting-SID list; WRITE_RESTRICTED by definition does not touch reads (E5).

### B5 Tooling to measure the attack surface (primary: Project Zero)
URL: https://projectzero.google//2015/11/windows-sandbox-attack-surface-analysis.html (2015-Nov-18) and https://github.com/google/sandbox-attacksurface-analysis-tools
Quote: "I've released my tools I use internally to test out sandboxed code and determine the likely attack surface exposed to an attacker if a sandboxed process is compromised." Includes a check for "allowed access to connecting or binding network sockets. This is for testing AppContainer lockdown." and checks of file system/registry/object-manager reachability for restricted, low IL and LowBox tokens. Quote: "And what if you mix both LowBox and restricted tokens? In general this is too complex to replicate accurately; fortunately, Windows provides a means of calculating the granted access to a resource." => This is the direct measurement the primer lacks (enumerate what a candidate token can write/read on THIS machine).

### B6 Dedicated standard user account - what Microsoft services
From E10 (MSRC criteria): "User boundary: A user cannot access or tamper with the code and data of another user without being authorized. Intent is to service: Yes". "Windows Resource Access Control: An identity (user, group) cannot access or tamper with a resource (file, named pipe, etc.) unless explicitly authorized to do so. Yes". Both mean: a bug that lets blarai-coder read the operator's files WITHOUT an ACL granting it IS a serviced vulnerability. BUT: an ACL that grants Users / Authenticated Users / Everyone access is "explicitly authorized": a writable-by-Users folder is configuration, not a vulnerability (consistent with the Chromium assumption "no critical resources with misconfigured security"). The #1678/#1686/#1689/#1692 findings are of that class: Microsoft will not service them; they are BlarAI's to close. [DERIVED from the criteria text; the page has no sentence about folder ACL misconfiguration.]
Direct evidence on this box (E11): `C:\` carries Authenticated Users (OI)(CI)(IO)(M); `C:\ProgramData` carries Users (CI)(WD,AD,WEA,WA); Windows, Program Files, System32 carry Users (RX).
Third-party examples of the class (SUMMARY ONLY via search results, not read): weak %PROGRAMDATA% folder permissions overwriting system files (CVE-2020-13149, MSI Dragon Center); DLL planting in writable ProgramData subfolders to reach SYSTEM; scheduled-task / service-path / file-ACL hunting (CVE-2024-28827 Checkmk). Underlying technique documented by P0: https://projectzero.google/2018/04/windows-exploitation-tricks-exploiting.html (2018-Apr-18) "A common way of exploiting arbitrary file writes is to perform DLL hijacking" (READ intro only). Services, scheduled tasks and installers that run as SYSTEM and read from a Users-writable path are the escalation route; that is a bug in the third-party/inbox component, serviced if inbox, not if third-party.

### B7 What Microsoft's servicing criteria do NOT list (E10)
Restricted tokens, Low integrity level / MIC, WRITE_RESTRICTED, job objects, "standard user -> administrator" as its own row: none named. Rule on the page: "By default, components are not considered boundaries unless explicitly named as such." UAC is named as NOT serviced. So: a restricted-token or low-IL-only escape that stays inside the same user is, by this page, not an intended-to-service boundary; the AppContainer sandbox boundary and the User boundary are. (Counter-evidence: CVE-2020-0981 restricted-token bug WAS fixed, April 2020, so in practice kernel bugs in token handling get serviced via the Kernel/Process boundary rows.)

### B8 New Microsoft sandbox API (2026) - READ (title/intro only)
URL: https://learn.microsoft.com/en-us/windows/win32/secauthz/createprocessinsandbox (src: win32/desktop-src/SecAuthZ/createprocessinsandbox.md, ms.date 6/1/2026)
Quote: "Creates a new process in a composable sandbox... These APIs launch a process with the containment properties described by a compiled sandbox specification." Marked "[!IMPORTANT] These APIs are experimental and subject to change." Also pages "App isolation" (win32 app isolation, SecAuthZ/app-isolation-*). Not evaluated for the coder; flag as an experimental, undocumented-stability surface; do not build on it.

---
# SUMMARY

READ (primary, full text): learn.microsoft.com pages: how-dacls-control-access-to-an-object; order-of-aces-in-a-dacl; ace-inheritance; access-tokens; restricted-tokens; CreateRestrictedToken; CreateAppContainerProfile; implementing-an-appcontainer; appcontainer-for-legacy-applications-; appcontainer-isolation; mandatory-integrity-control; app-container-sid-constants; capability-sid-constants; sid-strings; filtering-condition-identifiers-; filtering-condition-flags-; permitting-and-blocking-applications-and-users; NetworkIsolationSetAppContainerConfig; GetAppContainerNamedObjectPath; previous-versions hh780593 (loopback) and hh770532 (network capabilities); MSRC Windows Security Servicing Criteria (microsoft.com/msrc). Project Zero: 2021-08 network access, 2014-12 EPM, 2020-04 one-line, 2020-06 FF, 2016-01 Raising the Dead, 2015-11 attack surface tools (intro). Chromium docs/design/sandbox.md. Local icacls reads.
SUMMARY ONLY (search-result summaries, not opened): third-party CVE-2020-13149, CVE-2024-28827, CVE-2022-22715 (named-pipe LOCAL\ translation write-up), Microsoft Q&A on LPAC vs ALL_APPLICATION_PACKAGES, nono NEP-0005 (not touched by this task).
NOT FOUND in any Microsoft page: any statement of the text "ALL RESTRICTED APPLICATION PACKAGES" (only the SDDL "AC"/ANY_PACKAGE constant and the LPAC opt-out attribute); any elevation requirement for CreateAppContainerProfile or for CheckNetIsolation LoopbackExempt -a; how WFP's ALE_USER_ID treats restricting SIDs.

## Claim-by-claim verdict on the primer
| # | Primer claim (section) | Verdict | Basis |
|---|---|---|---|
| 1 | Token holds user SID, groups, privileges; Windows (not the program) checks it (1) | CONFIRMED | E4 |
| 2 | A child gets a copy of the parent's token (1) | CONFIRMED, with caveat | E4; default only. CreateProcessAsUser/Logon can give a different token if the caller has the privilege (B3: kernel's SeIsTokenAssignableToProcess is what stops a sandboxed process doing so) |
| 3 | "A refuse line beats an allow line" (2) | IMPRECISE | E1/E2: first match wins; canonical order puts explicit deny before explicit allow but explicit allow BEFORE inherited deny, and appending APIs do not enforce order. A deny on .ssh only beats an allow if the deny is explicit (or both inherited at the same level) and ordered first |
| 4 | Inheritance carries a parent's line into children (2) | CONFIRMED | E3; add: can be blocked (protected DACL). C:\ here has Authenticated Users Modify (OI)(CI)(IO) (E11), matching #1686 |
| 5 | ACLs cover files, folders, registry, not the network (2) | IMPRECISE | They cover all securable objects (processes, pipes, sections, COM servers); TCP/IP sockets are not gated by token (B4). WFP is the right tool: CONFIRMED (E9) |
| 6 | WFP can refuse "connections from this identity" (2) | CONFIRMED | FWPM_CONDITION_ALE_USER_ID (SD access check) and ALE_PACKAGE_ID (E9) |
| 7 | Dedicated account belongs to Users / Authenticated Users and inherits their grants (3) | CONFIRMED | E11 |
| 8 | Dedicated account does not hold against an attack on Windows itself (3) | CONFIRMED | but see table below: User boundary is a serviced boundary (E10) |
| 9 | Restricted token: deny-only groups, strip privileges, second SID list, both lists must allow (4) | CONFIRMED | E5, near-verbatim |
| 10 | Simple restricted token removes admin power and little else (4) | CONFIRMED | DISABLE_MAX_PRIVILEGE disables all but SeChangeNotify; deny-only groups; no restricting SIDs means no file confinement (E5, B4) |
| 11 | Stricter form (second list) can confine writes (4) | CONFIRMED (and can confine reads) | WRITE_RESTRICTED applies list to writes only (E5); full list confines reads too (B4, Chromium token) |
| 12 | Restricted token needs no extra account/login, per launch (4) | CONFIRMED | E5: ordinary applications can create restricted processes; no SE_ASSIGNPRIMARYTOKEN needed |
| 13 | "A network rule aimed at this identity would hit you too" (4) | NOT IN DOCS | ALE_USER_ID evaluates the token against an SD (E9). Docs do not say how restricting SIDs are treated. Unproven either way; testable with one filter |
| 14 | AppContainer: usual badge check plus the container identity (5) | CONFIRMED | E7 dual-principal, intersection |
| 15 | "A folder that merely allows all signed-in users does not admit it; the folder has to name the container" (5) | WRONG as stated | ALL APPLICATION PACKAGES (SECURITY_BUILTIN_PACKAGE_ANY_PACKAGE, SDDL "AC") admits EVERY AppContainer, and ALL RESTRICTED APPLICATION PACKAGES admits LPAC; both are granted (RX) on C:\Windows, C:\Program Files, System32 here (E11). Users/Authenticated Users alone do not admit it: that half is CONFIRMED |
| 16 | AppContainer "starts with nothing" (1, 5, table) | WRONG/IMPRECISE | E7: "Regular AppContainers are granted access to certain system files/directories, common registry keys and COM objects"; File isolation: "Read-only access is less restricted." Only LPAC (opt-out of ALL APPLICATION PACKAGES) is close to nothing, and even LPAC reads where ALL RESTRICTED APPLICATION PACKAGES is granted (E11) |
| 17 | No internet unless granted; network is a permission (5) | CONFIRMED | E7, E8 |
| 18 | Localhost blocked unless exemption set (5) | CONFIRMED | E8 (Win8-era page), B1 (P0, current behaviour) |
| 19 | (not in primer) exemption requires admin | CONFIRMED by P0, NOT IN MS DOCS | B1 "administrator only API"; MS pages silent. Reaching the model over localhost therefore needs a one-time admin step (or the model endpoint must not be on loopback) |
| 20 | Low trust level; private registry and object names (5) | CONFIRMED | E7 (low IL always), E12; but low IL read access to most files remains (B4) |
| 21 | CreateAppContainerProfile: no admin / per launch (5, table) | NOT IN DOCS (admin); per-launch IMPRECISE | E6: per-user, persistent profile; no elevation statement either way; per-launch only if created and deleted each time |
| 22 | Every folder the tools need must be granted by name (5) | CONFIRMED | E7 DACL grants through the package SID; ALL APPLICATION PACKAGES covers system locations only |
| 23 | "Most developer tools break"; "high setup, severe damage" (5) | NOT IN DOCS | empirical; primer itself says web research, not tested |
| 24 | WFP can target AppContainer: "open question in nono's proposal" (6) | RESOLVED: YES | FWPM_CONDITION_ALE_PACKAGE_ID "The security identifier (SID) of an app container" (E9); Windows' own filters use it (B1) |
| 25 | "Stops a Windows exploit: no" for all three (6) | IMPRECISE | "No" = no guarantee against an unpatched bug. Microsoft states intent to service AppContainer sandbox and user-boundary breaks (E10); restricted token and low IL are not named boundaries (B7); real escapes exist for each (B2, B3). A VM is also a serviced boundary (primer is right that a VM is the stronger option) |

## Servicing-boundary table (MSRC criteria, E10)
| Mechanism | Named serviced boundary? | Text |
|---|---|---|
| Dedicated standard user account | YES: "User boundary" and "Windows Resource Access Control" (feature) | "A user cannot access or tamper with the code and data of another user without being authorized." Misconfigured ACLs that authorize Users/Authenticated Users are not vulnerabilities |
| AppContainer | YES: "AppContainer sandbox boundary" | "cannot access or tamper with code and data outside of the sandbox based on the container capabilities" |
| Restricted token (CreateRestrictedToken) | NOT NAMED | page rule: not a boundary unless explicitly named |
| Low integrity level / MIC | NOT NAMED | same |
| UAC | NAMED NOT SERVICED (defense in depth) | "Any vulnerability or bypass... will not be serviced by default" |
| Hyper-V VM | YES: "Virtual machine boundary" | includes Hyper-V Isolated Containers |
| Windows Server Containers | NAMED NOT a boundary | shared kernel |

## Top bypass classes per mechanism
- Dedicated user: (1) broad-group grants: Users / Authenticated Users / Everyone / ALL APPLICATION PACKAGES on folders, with C:\ root Authenticated Users Modify inherited by new top-level folders and ProgramData subfolders writable by Users (E11); (2) SYSTEM services, scheduled tasks, installers reading from user-writable paths (DLL hijack, symlink and arbitrary-file-write chains, P0 2018); (3) kernel/LPE bugs (serviced under User/Kernel boundary); (4) non-securable resources: TCP/IP is not token-gated, so network needs WFP (B4); (5) same-user attack surface the account shares by group (shares, pipes, COM with Everyone launch rights).
- Restricted token: (1) kernel token-handling bugs (CVE-2020-0981, B3); (2) shared desktop / window messages (MS warning E5, Chromium alt desktop B4); (3) sibling processes opening each other via default DACL (CVE-2020-12388 class, B3); (4) restricting-SID list too permissive or WRITE_RESTRICTED only (reads open); (5) no network gating; (6) job object / child-process limits are what stops spawning an unrestricted process, not the token.
- AppContainer: (1) weak ACLs on processes/objects the same user owns, because capability and ALL APPLICATION PACKAGES SIDs are matched (CVE-2014-6350 class, B2); (2) COM/RPC brokers with Everyone or AC launch/activation permissions (P0 2018 COM series, SUMMARY ONLY); (3) firewall configuration: WontFix issue 2207, internetClient reaching private ranges, undocumented loopback-by-capability trick, server-capability misuse (B1); (4) the loopback exemption itself is an administrator-only debug facility (B1); (5) shared named pipes; (6) kernel bugs in the AppContainer path (serviced).
- Common to all three: none stops an in-kernel exploit; AppContainer and user boundary are serviced, others are not named.

## 10-line report summary: see final message.

## ADDENDUM (lead request): deny ACEs naming a package/capability SID in the AppContainer pass

Result: NO primary source found that states how a deny ACE naming a package SID or capability SID is handled in the AppContainer (lowbox) access-check pass.
Searched/READ: Microsoft win32 pages (how-dacls-control-access, implementing-an-appcontainer, appcontainer-isolation, legacy-apps, restricted-tokens) - none mention deny ACEs for package/capability SIDs. Project Zero 2014-12 EPM post (READ): describes two checks and AND of the granted sets, then says "(we're going to ignore deny ACEs as they're not relevant to this discussion)" - i.e. the author deliberately did not specify deny behaviour. Yason, BlackHat Asia 2014 whitepaper (READ via pdftotext): says only that a securable object "would need to have an additional access control entry for any of the following: The AppContainer; "ALL APPLICATION PACKAGES" (S-1-15-2-1); A capability that matches one of the AppContainer's capabilities" - allow-side only. Chromium docs/design/sandbox.md (READ): no deny discussion.
Not opened / SUMMARY ONLY: Windows Security Internals ch.7 (Forshaw), NtObjectManager source, ntdoc NtCreateLowBoxToken (HTTP 503), the book excerpt URL I had returned 404. A search-result paraphrase of Forshaw's book says the lowbox check "ignore[s] all regular user and group SIDs... treating them as deny-only SIDs" - SUMMARY ONLY, unverified, and it concerns the user/group SIDs, not package SIDs.
Secondary, READ: Electron PR #54382 (github.com/electron/electron/pull/54382, gh api): "Windows checks a restricted token against a DACL containing any AppContainer package SID (S-1-15-2-*) as if it were an AppContainer: only ALL APPLICATION PACKAGES or ALL RESTRICTED APPLICATION PACKAGES can grant." (an observation by Electron authors on a VM; allow-side; says nothing about deny.)

Check on the measurement itself (derived, not documented): in the SDDL rights string "DCLCRPCR" the tokens are DC, LC, RP, CR. Per ace-strings.md (READ) these are SDDL_DELETE_CHILD = ADS_RIGHT_DS_DELETE_CHILD, SDDL_LIST_CHILDREN = ADS_RIGHT_ACTRL_DS_LIST, SDDL_READ_PROPERTY, SDDL_CONTROL_ACCESS. The numeric ADS values (CC 0x1, DC 0x2, LC 0x4, RP 0x10, CR 0x100) are from my memory of ads headers, not from that page; with them the deny mask = 0x116. On a directory 0x2 is FILE_ADD_FILE (= FILE_WRITE_DATA's bit), 0x4 is FILE_ADD_SUBDIRECTORY (= FILE_APPEND_DATA's bit). So IF those values hold, the deny ACE DOES cover the bit 0x2 that was requested and the result would be a real surprise; if the SDDL parser did not map them that way, the deny never covered write-data and nothing is surprising. Cheapest discriminator: print the numeric AccessMask of the parsed deny ACE (GetAce / Get-NtSecurityDescriptor), and rerun with the deny mask set to 0x2 only, and with the deny naming a capability SID, and with the deny naming the user SID instead of the package SID as the control. Also run the same AccessCheck with the allow-for-package ACE removed (expect deny of write) to show the grant comes from that ACE and the deny is the thing being ignored.
