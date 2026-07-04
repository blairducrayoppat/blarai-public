using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using System.Runtime.InteropServices.WindowsRuntime;
using Windows.Storage.Streams;

namespace BlarAI.Desktop.Services;

/// <summary>
/// WinUI display seam partial of <see cref="ImageResolver"/>. This file contains
/// the members that depend on WinUI / Windows.Storage.Streams: the async
/// <see cref="ResolveAsync"/> live-pixel seam (decoded-bytes → BitmapImage) and
/// the superseded synchronous <see cref="Resolve"/> stub. The dependency-free
/// id-gate members (<c>Scheme</c>, <c>IsImageRef</c>, <c>IsValidImageId</c>,
/// <c>ExtractImageId</c>, <c>EscapeAlt</c>) live in ImageResolver.Core.cs so they
/// can be compiled into the headless xUnit test project without dragging in the
/// Windows App SDK workload.
///
/// LIVE-PIXEL RENDER (UC-010 #666/#665 Pass B): the inline-image render path is
/// WIRED. <see cref="MarkdownBlock"/> id-gates a <c>blarai-img://&lt;id&gt;</c>
/// ref, resolves the decrypted PNG bytes through the backend IMAGE_RESOLVE
/// corridor (<c>BackendClient.ResolveImageAsync</c>, injected as
/// <c>MarkdownBlock.ImageBytesResolver</c>), and feeds those bytes to
/// <see cref="ResolveAsync"/> to build the display-only <see cref="ImageSource"/>.
/// The decrypt happens in the AO process (the encrypted store is AO-resident); the
/// bytes arrive over the pipe leg already-decrypted and are NEVER written to disk
/// on this path. The Source is ALWAYS an in-memory <see cref="BitmapImage"/> —
/// never a Uri / network / file / data: source — so display stays strictly local.
///
/// WHAT IS STILL WELDED is the image INGEST/STORE path (UC-003), not display: the
/// fetch/store limbs stay shut by the image-specific locks (the adjudicator's
/// image-purpose-deny BED-1 + <c>[knowledge].images_enabled=false</c>). UC-010
/// GENERATED images, by contrast, are live (<c>[image_generation].enabled=true</c>)
/// and ARE resolvable through this seam. A ref with no decryptable bytes upstream
/// (unknown id, quarantine, disabled store) resolves to <c>null</c> and the caller
/// renders the inert alt-text placeholder (fail-closed). The headless id-gate
/// coverage is in ImageResolver.Core.cs + the xUnit test project
/// (services/ui_winui/tests/); the live render itself is confirmed on-hardware.
/// </summary>
public static partial class ImageResolver
{
    /// <summary>
    /// SUPERSEDED synchronous stub. The live inline-image path is now async
    /// (<see cref="MarkdownBlock.ImageBytesResolver"/> → <see cref="ResolveAsync"/>):
    /// the decrypted bytes arrive over the IMAGE_RESOLVE pipe corridor, which is
    /// inherently asynchronous, so a synchronous "resolve a ref to an ImageSource"
    /// has no live implementation and no caller. Retained only so any stray
    /// synchronous call site fails CLOSED (a null source → alt placeholder) rather
    /// than not compiling; new code MUST use the async seam. Returns <c>null</c>
    /// for any input: a non-image scheme / forged id has no id; a well-formed ref
    /// cannot be resolved synchronously here.
    /// </summary>
    public static ImageSource? Resolve(string? url)
    {
        // No synchronous resolve exists: the bytes come from the async corridor.
        // Returning null keeps any legacy caller fail-closed (alt placeholder).
        _ = ExtractImageId(url);  // shape-gate kept for parity; result unused.
        return null;
    }

    /// <summary>
    /// Live-pixel seam: build a display-only <see cref="BitmapImage"/> from an
    /// already-decrypted PNG byte buffer, using an
    /// <see cref="InMemoryRandomAccessStream"/> as the source so no network or
    /// file-system path is ever involved (the source is always an in-memory
    /// buffer, never a Uri / network / data: source). Fail-closed to <c>null</c>
    /// on <c>null</c>/empty/corrupt input.
    ///
    /// The bytes are supplied by the IMAGE_RESOLVE corridor
    /// (<c>BackendClient.ResolveImageAsync</c>); the decrypt happens AO-side, so
    /// this method only DECODES already-decrypted bytes. Called by
    /// <see cref="MarkdownBlock"/> on the UI thread (SetSourceAsync must run on the
    /// thread that will display the bitmap). Headless xUnit coverage is the id-gate
    /// (ImageResolver.Core.cs — this WinUI-dependent decode is not headless-testable
    /// and is confirmed on-hardware).
    /// </summary>
    public static async System.Threading.Tasks.Task<ImageSource?> ResolveAsync(byte[]? pngBytes)
    {
        if (pngBytes is null || pngBytes.Length == 0) return null;
        try
        {
            var bitmap = new BitmapImage();
            using var stream = new InMemoryRandomAccessStream();
            await stream.WriteAsync(pngBytes.AsBuffer()).AsTask().ConfigureAwait(false);
            stream.Seek(0);
            await bitmap.SetSourceAsync(stream).AsTask().ConfigureAwait(false);
            return bitmap;
        }
        catch
        {
            // Corrupt or unrecognised image bytes: fail closed, show alt placeholder.
            return null;
        }
    }
}
