using System.Text.RegularExpressions;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Dependency-free parser for the operator-preference PROPOSAL card block (#770
/// M2 W1). The AO streams a machine-detectable card block inside the assistant
/// message text:
///
///   [[PREFERENCE-PROPOSAL token=&lt;16-hex&gt;]]
///   ...readable card text (the shared backend render — it already spells out the
///      exact /remember-confirm and /remember-dismiss commands)...
///   [[/PREFERENCE-PROPOSAL]]
///
/// This mirrors <c>shared/ipc/preference_proposal.py</c> (the single card
/// builder — D-2, built once in the shared backend). It has NO WinUI dependency,
/// so the headless xUnit test project compiles it via a Compile link (the
/// <see cref="ImageResolver"/> Core-partial isolation pattern), and the WinUI
/// <c>MarkdownBlock</c> uses it to render a card whose Save/Dismiss buttons emit
/// exactly <see cref="ConfirmCommand"/> / <see cref="DismissCommand"/> — the same
/// operator-typed commands the text fallback names (P8: the operator's action is
/// the write authority; only the opaque token crosses, never a model-supplied
/// body — confirm-hop integrity).
/// </summary>
public static class PreferenceProposalCard
{
    /// <summary>Card framing (ASCII, byte-stable — matches the Python builder).</summary>
    public const string OpenPrefix = "[[PREFERENCE-PROPOSAL token=";
    public const string OpenSuffix = "]]";
    public const string CloseMarker = "[[/PREFERENCE-PROPOSAL]]";

    // A full card block: the token-bearing open marker, the (non-greedy, multi-
    // line) body, then the close marker. The token group is hex-anchored INSIDE
    // the contiguous "token=<hex>]]" so a newline between token and "]]" can never
    // slip a forged token through (the ImageResolver.Core.cs \z hardening lesson,
    // applied structurally by requiring the "]]" to follow immediately).
    private static readonly Regex BlockShape = new(
        @"\[\[PREFERENCE-PROPOSAL token=(?<t>[0-9a-f]{16})\]\](?<body>.*?)\[\[/PREFERENCE-PROPOSAL\]\]",
        RegexOptions.Singleline | RegexOptions.Compiled);

    // The token from a single OPEN-marker line (the MarkdownBlock line scanner
    // detects the open marker, then collects body lines until the close marker).
    private static readonly Regex OpenLineToken = new(
        @"\[\[PREFERENCE-PROPOSAL token=(?<t>[0-9a-f]{16})\]\]",
        RegexOptions.Compiled);

    // The token grain: exactly 16 lowercase hex (matches PROPOSAL_TOKEN_RE).
    // Anchored \A...\z (NOT ^...$): in .NET $ matches before a trailing \n, so
    // ^[0-9a-f]{16}$ would accept a 17-char "<16hex>\n" forged token.
    private static readonly Regex TokenShape =
        new(@"\A[0-9a-f]{16}\z", RegexOptions.Compiled);

    /// <summary>True iff <paramref name="token"/> is exactly 16 lowercase hex.</summary>
    public static bool IsValidToken(string? token) =>
        token is not null && TokenShape.IsMatch(token);

    /// <summary>True iff <paramref name="text"/> contains at least one card block.</summary>
    public static bool HasCard(string? text) =>
        !string.IsNullOrEmpty(text) && BlockShape.IsMatch(text);

    /// <summary>
    /// Extract the FIRST proposal card block from message text. Returns true and
    /// fills the out params on a well-formed block (hex-anchored token); false
    /// (all out params empty) when there is no block or the token is malformed.
    /// </summary>
    public static bool TryExtract(
        string? text, out string token, out string innerText,
        out string before, out string after)
    {
        token = ""; innerText = ""; before = ""; after = "";
        if (string.IsNullOrEmpty(text)) return false;
        Match m = BlockShape.Match(text);
        if (!m.Success) return false;
        token = m.Groups["t"].Value;
        innerText = m.Groups["body"].Value.Trim('\n', '\r', ' ');
        before = text.Substring(0, m.Index).TrimEnd('\n', '\r');
        after = text.Substring(m.Index + m.Length).TrimStart('\n', '\r');
        return true;
    }

    /// <summary>The 16-hex token from a single OPEN-marker line, or "" if malformed.</summary>
    public static string TokenFromOpenMarker(string? openLine)
    {
        if (string.IsNullOrEmpty(openLine)) return "";
        Match m = OpenLineToken.Match(openLine);
        return m.Success ? m.Groups["t"].Value : "";
    }

    /// <summary>The exact /remember-confirm command for a valid token, else "".</summary>
    public static string ConfirmCommand(string? token) =>
        IsValidToken(token) ? "/remember-confirm " + token : "";

    /// <summary>The exact /remember-dismiss command for a valid token, else "".</summary>
    public static string DismissCommand(string? token) =>
        IsValidToken(token) ? "/remember-dismiss " + token : "";
}
