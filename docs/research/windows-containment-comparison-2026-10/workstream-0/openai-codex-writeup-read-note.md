# OpenAI Codex Windows sandbox write-up: read record (#1740)

- **Article:** "Building a safe, effective sandbox to enable Codex on Windows", David Wiesen (Member of
  Technical Staff), OpenAI, dated May 13, 2026. https://openai.com/index/building-codex-windows-sandbox/
- **How it was read:** `curl` and the fetch tool both received HTTP 403 (recorded as NOT READ in
  `ws0-codex-mxc.md` line 30, which was true when that agent finished). The lead session then opened the page in a
  Playwright browser on 2026-10-10 at about 22:25 -04:00 and read the full article text (about 22,000
  characters). The page snapshot the browser wrote was scratch outside the repository; this note banks the
  citation and the short quotes the report relies on, not the article.
- **Quotes relied on** (verbatim, short):
  - On AppContainer: "Codex is not one tightly scoped app." ... "that made AppContainer the wrong shape for the problem."
  - On the network fence: "Windows doesn't allow matching a firewall rule to the non-principal identity of a restricted token."
  - On the unelevated mode's network control: "it was still only advisory."
  - On the elevated design: the restricted token's list is "[Everyone, Logon, Synthetic]", and its principal is "one of two local users created by Codex itself".
- **What the article does NOT say:** it speaks of Windows Firewall rules; it does not state whether a raw WFP
  filter with an `ALE_USER_ID` security descriptor can single out a restricted token. That stays open for
  phase 2 (report section 6).
