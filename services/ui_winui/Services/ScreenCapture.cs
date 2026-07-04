using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Primary-screen screenshot capture (Phase 4). Saves a PNG to a temp path the
/// caller then hands to the backend's store_attachment (which copies it into
/// userdata/). Vision is still deferred, so the captured image is store-only —
/// the point of shipping it now is to prime the experience and make the
/// eventual vision integration a backend-only change.
/// </summary>
public static class ScreenCapture
{
    [DllImport("user32.dll")] private static extern int GetSystemMetrics(int nIndex);
    private const int SM_CXSCREEN = 0;
    private const int SM_CYSCREEN = 1;

    /// <summary>
    /// Capture the primary screen to a PNG under the temp folder and return its
    /// path. The caller is responsible for moving/copying it into userdata/
    /// (via the backend) and for any pre-capture UI hiding.
    /// </summary>
    public static string CapturePrimaryScreenToTemp(string timestampToken)
    {
        int width = GetSystemMetrics(SM_CXSCREEN);
        int height = GetSystemMetrics(SM_CYSCREEN);
        if (width <= 0 || height <= 0) { width = 1920; height = 1080; }

        using var bmp = new Bitmap(width, height, PixelFormat.Format32bppArgb);
        using (var g = Graphics.FromImage(bmp))
        {
            g.CopyFromScreen(0, 0, 0, 0, new Size(width, height), CopyPixelOperation.SourceCopy);
        }

        string path = Path.Combine(
            Path.GetTempPath(), $"BlarAI-screenshot-{timestampToken}.png");
        bmp.Save(path, ImageFormat.Png);
        return path;
    }
}
