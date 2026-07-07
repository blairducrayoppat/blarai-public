using BlarAI.Desktop.Services;
using Xunit;

namespace BlarAI.Desktop.Tests;

/// <summary>
/// Headless coverage for the inline-image RENDER-PATH GATE (UC-010 #666/#665 Pass
/// B). The renderer (MarkdownBlock.BuildImageInline) decides — synchronously,
/// before any async resolve round-trip — whether a ![alt](url) is a legitimate
/// image ref that may proceed to the resolve corridor, or must degrade to an inert
/// alt-text placeholder. That decision is EXACTLY
/// <c>ImageResolver.ExtractImageId(url) is not null</c>: a well-formed
/// <c>blarai-img://&lt;32-lowercase-hex&gt;</c> ref proceeds; everything else
/// (other schemes, forged / malformed ids) returns null and never starts a
/// resolve. These tests lock that gate from the render-path's point of view.
///
/// WHAT IS NOT (and cannot be) COVERED HERE: the async fill itself
/// (MarkdownBlock.FillImageAsync) and the byte→BitmapImage decode
/// (ImageResolver.ResolveAsync) are WinUI-dependent (Image / InlineUIContainer /
/// DispatcherQueue / BitmapImage / InMemoryRandomAccessStream) and live in the
/// app project's WinUI partials, which this STRICTLY-ISOLATED test project does
/// not reference (it compiles only ImageResolver.Core.cs — see the .csproj). Their
/// fail-closed behaviour (a null/empty/over-cap resolve result OR a corrupt decode
/// → alt placeholder; Source is always an in-memory BitmapImage, never a Uri) is
/// confirmed on-hardware at the live-pixel render. ResolveAsync's own null-on-
/// null/empty contract is asserted structurally (it early-returns null before any
/// WinRT call) but is not unit-exercised headless for the same isolation reason.
/// </summary>
public class InlineImageRenderGateTests
{
    private const string FixedId = "0123456789abcdef0123456789abcdef";

    /// <summary>
    /// Mirrors MarkdownBlock.BuildImageInline's synchronous gate: a ref proceeds
    /// to the async resolve iff ExtractImageId returns a non-null id. This is the
    /// single source of the render-path branch, so testing it here tests the gate
    /// the renderer actually applies.
    /// </summary>
    private static bool WouldStartResolve(string url) =>
        ImageResolver.ExtractImageId(url) is not null;

    // ── Legitimate refs proceed to the resolve corridor ───────────────────────

    [Fact]
    public void ValidBlaraiImgRef_ProceedsToResolve()
    {
        Assert.True(WouldStartResolve(ImageResolver.Scheme + FixedId));
    }

    [Fact]
    public void ValidBlaraiImgRef_UppercaseScheme_ProceedsToResolve()
    {
        // The scheme is matched case-insensitively; the id stays lowercase hex.
        Assert.True(WouldStartResolve("BLARAI-IMG://" + FixedId));
        // And the extracted id is the canonical lowercase id (what gets resolved).
        Assert.Equal(FixedId, ImageResolver.ExtractImageId("BLARAI-IMG://" + FixedId));
    }

    // ── Everything else degrades to the inert alt placeholder ──────────────────

    [Theory]
    [InlineData("https://example.com/cat.png")]   // remote http(s) — never fetched
    [InlineData("http://10.0.0.1/x.png")]
    [InlineData("data:image/png;base64,AAAA")]     // inline data: payload
    [InlineData("javascript:alert(1)")]            // active scheme
    [InlineData("file:///C:/secret.png")]          // local file scheme
    [InlineData("vbscript:msgbox(1)")]
    [InlineData("blarai-img://../../etc/passwd")]  // path traversal in the id slot
    [InlineData("blarai-img://0123456789ABCDEF0123456789ABCDEF")] // uppercase id
    [InlineData("blarai-img://0123456789abcdef0123456789abcde")]  // 31 chars (short)
    [InlineData("blarai-img://0123456789abcdef0123456789abcdef0")] // 33 chars (long)
    [InlineData("blarai-img://0123456789abcdef0123456789abcde?x=1")] // query smuggle
    [InlineData("blarai-img://0123456789abcdef0123456789abcde#frag")] // fragment
    [InlineData("blarai-img://")]                  // empty id
    [InlineData("blarai-img://blarai-img://0123456789abcdef0123456789abcdef")] // nested
    public void NonImageOrForgedRef_DegradesToPlaceholder(string url)
    {
        Assert.False(WouldStartResolve(url));
    }

    [Fact]
    public void Null_DegradesToPlaceholder()
    {
        Assert.False(WouldStartResolve(null!));
    }

    [Fact]
    public void Empty_DegradesToPlaceholder()
    {
        Assert.False(WouldStartResolve(""));
    }

    // ── The render-path's alt text is always HTML-escaped (defense-in-depth) ───

    [Fact]
    public void RenderedAlt_IsHtmlEscaped()
    {
        // BuildImageInline shows "[image: <escaped-alt>]" for both the placeholder
        // and the fail-closed swap; the alt is escaped so it can never smuggle
        // markup/active content even if reused in a markup-bearing sink.
        Assert.Equal("&lt;img src=x onerror=alert(1)&gt;",
            ImageResolver.EscapeAlt("<img src=x onerror=alert(1)>"));
    }

    // ── The superseded synchronous Resolve stub is a no-op (fail-closed) ───────
    //
    // Resolve(string?) is retained only so any stray synchronous caller fails
    // CLOSED (null source → placeholder). It lives in the WinUI partial (returns
    // ImageSource?), so it is not callable headless — but the contract is "always
    // null", which the render path no longer depends on (it uses the async seam).
    // No headless assertion is possible without the Windows App SDK; documented
    // here so a reviewer knows the omission is by isolation design, not oversight.
}
