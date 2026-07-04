using BlarAI.Desktop.Services;
using Xunit;

namespace BlarAI.Desktop.Tests;

/// <summary>
/// Headless id-gate tests for <see cref="ImageResolver"/> (Vikunja #665 item-1).
/// These tests cover the dependency-free members in ImageResolver.Core.cs ONLY —
/// the forged-id surface that must be denied at render time before any decrypt
/// round-trip is attempted. The WinUI display seam (Resolve / ResolveAsync) is
/// not testable headless and is reserved for the on-hardware go-live ceremony.
///
/// Key adversarial case: the trailing-newline test calls <c>IsValidImageId</c>
/// DIRECTLY (not <c>ExtractImageId</c>, which Trim()s the \n away and would
/// falsely accept the input). The \z anchor in the Regex is what stops this.
/// </summary>
public class ImageResolverIdGateTests
{
    // ── helpers ──────────────────────────────────────────────────────────────

    /// <summary>A canonical valid 32-lowercase-hex id (Guid.NewGuid().ToString("N") shape).</summary>
    private static string ValidId() => Guid.NewGuid().ToString("N"); // e.g. "550e8400e29b41d4a716446655440000"

    /// <summary>A fixed 32-lowercase-hex id for deterministic tests.</summary>
    private const string FixedId = "0123456789abcdef0123456789abcdef";

    private static string ValidRef(string? id = null) => ImageResolver.Scheme + (id ?? FixedId);

    // ── IsValidImageId — accept ───────────────────────────────────────────────

    [Fact]
    public void IsValidImageId_AcceptsGuidN()
    {
        // uuid4().hex produces Guid.NewGuid().ToString("N") — must accept.
        Assert.True(ImageResolver.IsValidImageId(ValidId()));
    }

    [Fact]
    public void IsValidImageId_AcceptsFixed32LowercaseHex()
    {
        Assert.True(ImageResolver.IsValidImageId(FixedId));
    }

    // ── IsValidImageId — reject ───────────────────────────────────────────────

    [Fact]
    public void IsValidImageId_RejectsUppercaseHex()
    {
        // uuid4().hex is always lowercase; uppercase is a forged / mis-encoded ref.
        Assert.False(ImageResolver.IsValidImageId("0123456789ABCDEF0123456789ABCDEF"));
    }

    [Fact]
    public void IsValidImageId_Rejects31Chars()
    {
        // One char short — wrong length.
        Assert.False(ImageResolver.IsValidImageId("0123456789abcdef0123456789abcde"));
    }

    [Fact]
    public void IsValidImageId_Rejects33Chars()
    {
        // One char over — wrong length.
        Assert.False(ImageResolver.IsValidImageId("0123456789abcdef0123456789abcdef0"));
    }

    [Fact]
    public void IsValidImageId_RejectsEmpty()
    {
        Assert.False(ImageResolver.IsValidImageId(""));
    }

    [Fact]
    public void IsValidImageId_RejectsNull()
    {
        Assert.False(ImageResolver.IsValidImageId(null));
    }

    [Fact]
    public void IsValidImageId_RejectsPathTraversal()
    {
        Assert.False(ImageResolver.IsValidImageId("../../etc/passwd"));
    }

    [Fact]
    public void IsValidImageId_RejectsDotDot()
    {
        Assert.False(ImageResolver.IsValidImageId(".."));
    }

    [Fact]
    public void IsValidImageId_RejectsQuerySmuggling()
    {
        // 31 hex chars + "?x=1" — query param smuggled after an almost-valid id.
        Assert.False(ImageResolver.IsValidImageId("0123456789abcdef0123456789abcde?x=1"));
    }

    [Fact]
    public void IsValidImageId_RejectsFragmentSmuggling()
    {
        // 31 hex chars + "#frag" — fragment smuggled after an almost-valid id.
        Assert.False(ImageResolver.IsValidImageId("0123456789abcdef0123456789abcde#frag"));
    }

    /// <summary>
    /// CRITICAL adversarial case: a 32-hex id followed by a trailing newline.
    /// In .NET, the <c>$</c> anchor matches BEFORE a trailing <c>\n</c>, so a
    /// naive <c>^[0-9a-f]{32}$</c> regex would silently accept this 33-char
    /// string. The <c>\z</c> anchor (absolute end-of-string) must reject it.
    ///
    /// IMPORTANT: call <c>IsValidImageId</c> DIRECTLY here, NOT <c>ExtractImageId</c>.
    /// ExtractImageId Trim()s the id string before validating, which would mask the
    /// \n and produce a false-accept — that would not be a real-world protection
    /// (the Trim call is in the URL-parsing path where the scheme is stripped, not
    /// in the id-gate path). The render-time caller passes raw ids; this gate must
    /// fire on the raw value.
    /// </summary>
    [Fact]
    public void IsValidImageId_RejectsTrailingNewline_ZAnchorNotDollar()
    {
        string forgedId = FixedId + "\n"; // 33 chars — looks like 32 hex + newline
        Assert.False(ImageResolver.IsValidImageId(forgedId));
    }

    // ── ExtractImageId ────────────────────────────────────────────────────────

    [Fact]
    public void ExtractImageId_ReturnsIdForValidRef()
    {
        string? result = ImageResolver.ExtractImageId(ValidRef());
        Assert.Equal(FixedId, result);
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForHttps()
    {
        Assert.Null(ImageResolver.ExtractImageId("https://example.com/img.png"));
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForDataUri()
    {
        Assert.Null(ImageResolver.ExtractImageId("data:image/png;base64,AAAA"));
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForJavascript()
    {
        Assert.Null(ImageResolver.ExtractImageId("javascript:alert(1)"));
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForNull()
    {
        Assert.Null(ImageResolver.ExtractImageId(null));
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForEmptyId()
    {
        // "blarai-img://" with nothing after — empty id, must reject.
        Assert.Null(ImageResolver.ExtractImageId(ImageResolver.Scheme));
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForPathTraversalId()
    {
        Assert.Null(ImageResolver.ExtractImageId(ImageResolver.Scheme + "../x"));
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForUppercaseId()
    {
        // Scheme is accepted case-insensitively, but the id must be lowercase hex.
        Assert.Null(ImageResolver.ExtractImageId(ImageResolver.Scheme + "0123456789ABCDEF0123456789ABCDEF"));
    }

    [Fact]
    public void ExtractImageId_ReturnsNullForNestedScheme()
    {
        // Nested scheme: blarai-img://blarai-img://<32hex>
        // The outer scheme is stripped, leaving "blarai-img://<32hex>" as the id,
        // which fails IsValidImageId (not 32 lowercase hex).
        string nested = ImageResolver.Scheme + ImageResolver.Scheme + FixedId;
        Assert.Null(ImageResolver.ExtractImageId(nested));
    }

    // ── IsImageRef ────────────────────────────────────────────────────────────

    [Fact]
    public void IsImageRef_TrueForBlaraiImgScheme()
    {
        Assert.True(ImageResolver.IsImageRef("blarai-img://abc"));
    }

    [Fact]
    public void IsImageRef_TrueForUppercaseScheme()
    {
        // Scheme check is case-insensitive (StringComparison.OrdinalIgnoreCase).
        Assert.True(ImageResolver.IsImageRef("BLARAI-IMG://abc"));
    }

    [Fact]
    public void IsImageRef_FalseForHttp()
    {
        Assert.False(ImageResolver.IsImageRef("http://x"));
    }

    [Fact]
    public void IsImageRef_FalseForNull()
    {
        Assert.False(ImageResolver.IsImageRef(null));
    }

    // ── EscapeAlt ─────────────────────────────────────────────────────────────

    [Fact]
    public void EscapeAlt_EncodesHtmlTags()
    {
        Assert.Equal("&lt;b&gt;x&lt;/b&gt;", ImageResolver.EscapeAlt("<b>x</b>"));
    }

    [Fact]
    public void EscapeAlt_ReturnsEmptyForEmpty()
    {
        Assert.Equal("", ImageResolver.EscapeAlt(""));
    }

    [Fact]
    public void EscapeAlt_ReturnsEmptyForNull()
    {
        Assert.Equal("", ImageResolver.EscapeAlt(null));
    }
}
