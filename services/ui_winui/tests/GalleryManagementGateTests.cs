using BlarAI.Desktop.Services;
using Xunit;

namespace BlarAI.Desktop.Tests;

/// <summary>
/// Headless coverage for the gallery management CLIENT-SIDE GATE (UC-010 Phase 2,
/// #668). Before <c>BackendClient.MarkImageSavedAsync</c> / <c>DeleteImageAsync</c>
/// (and the gallery Save handler) make any round-trip, they refuse a malformed id
/// with the SAME shape check the resolve/render paths use —
/// <c>ImageResolver.IsValidImageId(id)</c> — so a forged id never reaches the
/// born-encrypted store's delete/mark legs. That decision is the single source of
/// the management-path branch, so testing it here tests the gate those methods
/// actually apply (defense-in-depth; the Python dispatcher re-gates server-side
/// with the same anchored 32-hex regex — see test_dispatcher_image_management.py).
///
/// WHAT IS NOT (and cannot be) COVERED HERE: <c>BackendClient</c> itself, the
/// <c>GeneratedImageMeta</c> JSON parse, and the <c>GalleryImageItem</c> view-model
/// are WinUI/pipe-dependent (PipeClient, Microsoft.UI.Xaml.Visibility / ImageSource)
/// and live in the app project, which this STRICTLY-ISOLATED test project does not
/// reference (it compiles only ImageResolver.Core.cs — see the .csproj). The
/// metadata-only list parse and the fail-closed manage semantics are covered on
/// the Python side; the WinUI compile + on-hardware run confirm the rest.
/// </summary>
public class GalleryManagementGateTests
{
    private const string FixedId = "0123456789abcdef0123456789abcdef";

    /// <summary>
    /// Mirrors the guard at the top of BackendClient.ManageAsync (and the gallery
    /// Save path): a manage round-trip proceeds iff the id is a well-formed
    /// uuid4().hex. This is the single source of that branch.
    /// </summary>
    private static bool WouldIssueManageRpc(string? imageId) =>
        ImageResolver.IsValidImageId(imageId);

    // ── A well-formed id is allowed through to the backend ─────────────────────

    [Fact]
    public void ValidId_ProceedsToManageRpc()
    {
        Assert.True(WouldIssueManageRpc(FixedId));
    }

    [Fact]
    public void GuidN_ProceedsToManageRpc()
    {
        Assert.True(WouldIssueManageRpc(System.Guid.NewGuid().ToString("N")));
    }

    // ── Every malformed / forged id is refused BEFORE any round-trip ───────────

    [Theory]
    [InlineData("")]                                       // empty
    [InlineData("0123456789abcdef0123456789abcde")]        // 31 chars (short)
    [InlineData("0123456789abcdef0123456789abcdef0")]      // 33 chars (long)
    [InlineData("0123456789ABCDEF0123456789ABCDEF")]       // uppercase
    [InlineData("../../etc/passwd")]                        // path traversal
    [InlineData("0123456789abcdef0123456789abcde?x=1")]    // query smuggle
    [InlineData("0123456789abcdef0123456789abcde#frag")]   // fragment smuggle
    [InlineData("blarai-img://0123456789abcdef0123456789abcdef")] // a full ref, not a bare id
    public void MalformedId_RefusedBeforeManageRpc(string imageId)
    {
        Assert.False(WouldIssueManageRpc(imageId));
    }

    [Fact]
    public void NullId_RefusedBeforeManageRpc()
    {
        Assert.False(WouldIssueManageRpc(null));
    }

    /// <summary>
    /// A 32-hex id with a trailing newline must be refused (the \z-anchor lesson):
    /// a naive ^…$ regex would accept <c>&lt;32hex&gt;\n</c>. The management gate
    /// passes the raw id through IsValidImageId, so the anchor is what protects it.
    /// </summary>
    [Fact]
    public void IdWithTrailingNewline_RefusedBeforeManageRpc()
    {
        Assert.False(WouldIssueManageRpc(FixedId + "\n"));
    }
}
