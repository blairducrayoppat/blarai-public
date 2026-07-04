using System.ComponentModel;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using BlarAI.Desktop.Dtos;

namespace BlarAI.Desktop.ViewModels;

/// <summary>
/// One tile in the generated-image gallery (UC-010 Phase 2, #668). Built from the
/// metadata-only <see cref="GeneratedImageMeta"/> row; the <see cref="Thumbnail"/>
/// is filled asynchronously AFTER construction (placeholder-then-fill) by
/// resolving the decrypted PNG bytes through the existing resolve corridor and
/// decoding them to an in-memory <see cref="ImageSource"/> — DISPLAY-ONLY, never a
/// Uri / network / file source (the same posture as the inline markdown render).
///
/// <see cref="Saved"/> is mutable and raises notifications so the saved-✓ /
/// encrypted-only-🔒 badge flips the instant the operator Saves a tile. The
/// Visibility projections are bound directly by x:Bind (no converter — a
/// Window-rooted XAML tree has no FrameworkElement lookup root for one; see
/// <see cref="MessageItem"/>).
/// </summary>
public sealed class GalleryImageItem : INotifyPropertyChanged
{
    public GalleryImageItem(GeneratedImageMeta meta)
    {
        ImageId = meta.ImageId;
        ByteSize = meta.ByteSize;
        CreatedAt = meta.CreatedAt;
        _saved = meta.Saved;
    }

    /// <summary>The opaque uuid4().hex handle (the id every Save/Delete rides).</summary>
    public string ImageId { get; }

    /// <summary>On-disk ciphertext size in bytes (a length(data) aggregate, no decrypt).</summary>
    public long ByteSize { get; }

    /// <summary>ISO-8601 creation timestamp string from the store.</summary>
    public string CreatedAt { get; }

    /// <summary>Short id prefix for the suggested save filename / a11y name.</summary>
    public string ShortId => ImageId.Length >= 8 ? ImageId[..8] : ImageId;

    // ── Mutable: saved state (flips the badge after a successful Save) ───────

    private bool _saved;
    /// <summary>True once the operator has saved this image to disk (badge = ✓).</summary>
    public bool Saved
    {
        get => _saved;
        set
        {
            if (_saved == value) return;
            _saved = value;
            OnChanged();
            OnChanged(nameof(SavedBadgeVisibility));
            OnChanged(nameof(LockBadgeVisibility));
        }
    }

    /// <summary>Green-check badge: shown only when the image has been saved.</summary>
    public Visibility SavedBadgeVisibility =>
        Saved ? Visibility.Visible : Visibility.Collapsed;

    /// <summary>Lock badge: shown only while the image is encrypted-only (unsaved).</summary>
    public Visibility LockBadgeVisibility =>
        Saved ? Visibility.Collapsed : Visibility.Visible;

    // ── Mutable: thumbnail (placeholder-then-fill) ──────────────────────────

    private ImageSource? _thumbnail;
    /// <summary>
    /// The decoded, display-only thumbnail (in-memory BitmapImage). Null until the
    /// async resolve fills it; stays null if the resolve produced no bytes (then
    /// the tile shows the placeholder and Save is disabled — Delete still works).
    /// </summary>
    public ImageSource? Thumbnail
    {
        get => _thumbnail;
        set
        {
            // Reference-compare is enough here (always a freshly-decoded bitmap).
            if (ReferenceEquals(_thumbnail, value)) return;
            _thumbnail = value;
            OnChanged();
            OnChanged(nameof(ThumbnailVisibility));
            OnChanged(nameof(PlaceholderVisibility));
        }
    }

    private bool _resolved;
    /// <summary>
    /// True once a resolve attempt produced renderable bytes. Drives
    /// <see cref="SaveEnabled"/>: a tile whose pixels could not be resolved (no
    /// bytes upstream / transient failure) must not offer Save (there is nothing
    /// to write), but Delete stays available so the operator can still remove it.
    /// Set alongside <see cref="Thumbnail"/> by the fill path.
    /// </summary>
    public bool Resolved
    {
        get => _resolved;
        set
        {
            if (_resolved == value) return;
            _resolved = value;
            OnChanged();
            OnChanged(nameof(SaveEnabled));
        }
    }

    public Visibility ThumbnailVisibility =>
        Thumbnail is not null ? Visibility.Visible : Visibility.Collapsed;
    public Visibility PlaceholderVisibility =>
        Thumbnail is null ? Visibility.Visible : Visibility.Collapsed;

    /// <summary>Save is offered only once renderable bytes exist for this image.</summary>
    public bool SaveEnabled => Resolved;

    // ── Friendly display string: size + date ────────────────────────────────

    /// <summary>e.g. "2.0 MB · 2026-06-17" (date-only, best-effort parse).</summary>
    public string SizeAndDate
    {
        get
        {
            string size = FormatSize(ByteSize);
            string date = FormatDate(CreatedAt);
            return string.IsNullOrEmpty(date) ? size : $"{size} · {date}";
        }
    }

    private static string FormatSize(long bytes)
    {
        if (bytes <= 0) return "—";
        if (bytes < 1024) return $"{bytes} B";
        double kb = bytes / 1024.0;
        if (kb < 1024) return $"{kb:0.#} KB";
        double mb = kb / 1024.0;
        return $"{mb:0.#} MB";
    }

    private static string FormatDate(string isoTimestamp)
    {
        if (string.IsNullOrWhiteSpace(isoTimestamp)) return "";
        return DateTimeOffset.TryParse(
            isoTimestamp, CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
            out var dto)
            ? dto.ToLocalTime().ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)
            : "";
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
