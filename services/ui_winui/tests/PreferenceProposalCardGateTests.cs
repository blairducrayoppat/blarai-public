using BlarAI.Desktop.Services;
using Xunit;

namespace BlarAI.Desktop.Tests;

/// <summary>
/// Headless coverage for the operator-preference PROPOSAL card parser (#770 M2
/// W1). The WinUI <c>MarkdownBlock</c> detects the streamed card block, extracts
/// its 16-hex staging token, and renders a card whose Save/Dismiss buttons emit
/// <c>PreferenceProposalCard.ConfirmCommand(token)</c> /
/// <c>DismissCommand(token)</c>. That token gate + command shaping is the pure
/// logic this project locks; it mirrors <c>shared/ipc/preference_proposal.py</c>
/// (the single card builder — D-2). The live card VISUAL (Border, buttons, the
/// send hop) is WinUI-dependent and confirmed on-hardware (C2), like the inline
/// image render.
/// </summary>
public class PreferenceProposalCardGateTests
{
    private const string FixedToken = "0123456789abcdef";

    private static string Block(string token, string body) =>
        $"[[PREFERENCE-PROPOSAL token={token}]]\n{body}\n[[/PREFERENCE-PROPOSAL]]";

    // ── Well-formed block extraction ─────────────────────────────────────────

    [Fact]
    public void ValidBlock_Extracts_Token_Body_And_Surrounds()
    {
        string text = "Here is a thought.\n" + Block(FixedToken, "Save this?") + "\nAnything else?";
        bool ok = PreferenceProposalCard.TryExtract(
            text, out string token, out string inner, out string before, out string after);
        Assert.True(ok);
        Assert.Equal(FixedToken, token);
        Assert.Equal("Save this?", inner);
        Assert.Equal("Here is a thought.", before);
        Assert.Equal("Anything else?", after);
    }

    [Fact]
    public void HasCard_TrueForBlock_FalseForPlainText()
    {
        Assert.True(PreferenceProposalCard.HasCard(Block(FixedToken, "x")));
        Assert.False(PreferenceProposalCard.HasCard("just a normal answer"));
        Assert.False(PreferenceProposalCard.HasCard(""));
        Assert.False(PreferenceProposalCard.HasCard(null));
    }

    [Fact]
    public void TokenFromOpenMarker_ReadsTheOpenLine()
    {
        Assert.Equal(
            FixedToken,
            PreferenceProposalCard.TokenFromOpenMarker(
                $"[[PREFERENCE-PROPOSAL token={FixedToken}]]"));
        Assert.Equal("", PreferenceProposalCard.TokenFromOpenMarker("[[PREFERENCE-PROPOSAL token=zzzz]]"));
        Assert.Equal("", PreferenceProposalCard.TokenFromOpenMarker(null));
    }

    // ── Token gate — forged / malformed tokens never yield a card ─────────────

    [Theory]
    [InlineData("0123456789abcde")]    // 15 hex — too short
    [InlineData("0123456789abcdef0")]  // 17 hex — too long
    [InlineData("0123456789ABCDEF")]   // uppercase — not the lowercase grain
    [InlineData("0123456789abcdeg")]   // non-hex char
    [InlineData("")]                   // empty
    public void MalformedToken_NoExtraction(string badToken)
    {
        Assert.False(PreferenceProposalCard.IsValidToken(badToken));
        bool ok = PreferenceProposalCard.TryExtract(
            Block(badToken, "body"), out _, out _, out _, out _);
        Assert.False(ok);
    }

    [Fact]
    public void TokenWithTrailingNewlineBeforeMarker_DoesNotMatch()
    {
        // A newline between the token and the closing "]]" breaks the contiguous
        // "token=<hex>]]" shape — no forged token slips through.
        string forged = "[[PREFERENCE-PROPOSAL token=" + FixedToken + "\n]]\nbody\n[[/PREFERENCE-PROPOSAL]]";
        Assert.False(PreferenceProposalCard.HasCard(forged));
    }

    // ── Command shaping — the buttons emit exactly these ──────────────────────

    [Fact]
    public void ConfirmAndDismiss_ProduceExactCommands()
    {
        Assert.Equal("/remember-confirm " + FixedToken,
            PreferenceProposalCard.ConfirmCommand(FixedToken));
        Assert.Equal("/remember-dismiss " + FixedToken,
            PreferenceProposalCard.DismissCommand(FixedToken));
    }

    [Fact]
    public void Commands_EmptyForMalformedToken()
    {
        Assert.Equal("", PreferenceProposalCard.ConfirmCommand("nope"));
        Assert.Equal("", PreferenceProposalCard.DismissCommand("nope"));
        Assert.Equal("", PreferenceProposalCard.ConfirmCommand(null));
    }

    [Fact]
    public void NoBlock_TryExtractFalse_AllEmpty()
    {
        bool ok = PreferenceProposalCard.TryExtract(
            "no card here", out string token, out string inner, out string before, out string after);
        Assert.False(ok);
        Assert.Equal("", token);
        Assert.Equal("", inner);
        Assert.Equal("", before);
        Assert.Equal("", after);
    }
}
