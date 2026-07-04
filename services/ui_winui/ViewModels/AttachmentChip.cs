using System.IO;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace BlarAI.Desktop.ViewModels;

/// <summary>
/// A first-class attachment rendered inline in the chat (and in the composer
/// before send) as a Gemini-style chip: a thumbnail for images, a file icon +
/// name for documents, a clip icon for video. The pixels are never read by
/// BlarAI yet (vision deferred); the chip is purely presentation over the
/// store-only attachment the backend already staged.
/// </summary>
public sealed class AttachmentChip
{
    public AttachmentChip(string filename, string mediaType, string userdataPath)
    {
        Filename = filename;
        MediaType = mediaType;
        UserdataPath = userdataPath;
    }

    public string Filename { get; }
    public string MediaType { get; }      // "text" | "image" | "video"
    public string UserdataPath { get; }   // absolute path inside userdata/ (for image thumbnails)

    public bool IsImage => MediaType == "image";

    public Visibility ThumbnailVisibility => IsImage ? Visibility.Visible : Visibility.Collapsed;
    public Visibility IconVisibility => IsImage ? Visibility.Collapsed : Visibility.Visible;

    /// <summary>Thumbnail image source for image attachments (null otherwise).</summary>
    public ImageSource? Thumbnail =>
        IsImage && !string.IsNullOrEmpty(UserdataPath) && File.Exists(UserdataPath)
            ? new BitmapImage(new Uri(UserdataPath))
            : null;

    /// <summary>Segoe Fluent glyph for non-image attachments.</summary>
    public string Glyph => MediaType switch
    {
        "video" => "",   // Video
        _ => "",          // Document
    };
}
