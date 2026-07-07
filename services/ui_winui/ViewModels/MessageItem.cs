using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using Microsoft.UI.Xaml;

namespace BlarAI.Desktop.ViewModels;

/// <summary>
/// One rendered chat message. <see cref="Text"/> is mutable and raises change
/// notifications so a streaming assistant reply updates live as tokens arrive.
/// </summary>
public sealed class MessageItem : INotifyPropertyChanged
{
    public MessageItem(string role, string text)
    {
        Role = role;
        _text = text;
    }

    public string Role { get; }

    public bool IsUser => Role == "user";
    public bool IsAssistant => Role == "assistant";

    /// <summary>Inline attachment chips shown with this message (user turns).</summary>
    public ObservableCollection<AttachmentChip> Attachments { get; } = new();

    // Visibility projections — bound directly by x:Bind so DataTemplates need
    // no {StaticResource} converter (converters require a FrameworkElement
    // lookup root, which a Window-rooted XAML tree does not provide).
    public Visibility UserVisibility => IsUser ? Visibility.Visible : Visibility.Collapsed;
    public Visibility AssistantVisibility => IsAssistant ? Visibility.Visible : Visibility.Collapsed;
    public Visibility TextVisibility =>
        string.IsNullOrEmpty(Text) ? Visibility.Collapsed : Visibility.Visible;
    // Per-message play button: assistant turns that actually have text (ADR-017).
    public Visibility PlayVisibility =>
        IsAssistant && !string.IsNullOrEmpty(Text) ? Visibility.Visible : Visibility.Collapsed;
    public Visibility DeniedVisibility => IsDenied ? Visibility.Visible : Visibility.Collapsed;
    public Visibility ReasonVisibility =>
        string.IsNullOrWhiteSpace(ReasonText) ? Visibility.Collapsed : Visibility.Visible;

    private string _text;
    public string Text
    {
        get => _text;
        set { if (_text != value) { _text = value; OnChanged(); OnChanged(nameof(TextVisibility)); OnChanged(nameof(PlayVisibility)); } }
    }

    private bool _isDenied;
    public bool IsDenied
    {
        get => _isDenied;
        set { if (_isDenied != value) { _isDenied = value; OnChanged(); OnChanged(nameof(DeniedVisibility)); } }
    }

    private string _reasonText = "";
    public string ReasonText
    {
        get => _reasonText;
        set { if (_reasonText != value) { _reasonText = value; OnChanged(); OnChanged(nameof(ReasonVisibility)); } }
    }

    // ── Ingest editable-preview state (#663 Workstream A) ────────────────
    // An ingest preview turn carries the cleaned article body so the operator
    // can trim noise/ads and approve the curated text. The Edit toggle swaps the
    // rendered MarkdownBlock for an editable markdown-source box; Approve and
    // Reject both go through the structured ingest_decide channel (Approve
    // carries the possibly-edited body).

    /// <summary>The pending document handle (opaque uuid); empty for normal turns.</summary>
    public string DocUuid { get; set; } = "";
    /// <summary>'paste' | 'file' | 'url' — the ingest source type, for context.</summary>
    public string SourceType { get; set; } = "";

    private bool _isIngestPreview;
    /// <summary>True when this assistant turn is an editable ingest preview.</summary>
    public bool IsIngestPreview
    {
        get => _isIngestPreview;
        set
        {
            if (_isIngestPreview == value) return;
            _isIngestPreview = value;
            OnChanged();
            OnChanged(nameof(IngestActionsVisibility));
            OnChanged(nameof(EditBoxVisibility));
            OnChanged(nameof(MarkdownVisibility));
        }
    }

    private bool _isEditing;
    /// <summary>Edit toggle: show the editable markdown-source box vs the render.</summary>
    public bool IsEditing
    {
        get => _isEditing;
        set
        {
            if (_isEditing == value) return;
            bool leavingEdit = _isEditing && !value;   // Done editing (true → false)
            _isEditing = value;
            // On "Done editing" of an ingest preview, fold the edited markdown
            // source back into the rendered field so the read-mode MarkdownBlock
            // (bound to Text) shows the OPERATOR'S edits, not the original
            // streamed body (#663 Workstream A). Approve still reads EditableBody,
            // so the data was always safe — this is the display-side sync that was
            // missing: the preview render diverged from the edit buffer. Text and
            // EditableBody are both markdown source for the same article, so the
            // copy renders the edits faithfully. Assigning through the Text setter
            // raises Text/TextVisibility/PlayVisibility for us (and no-ops if the
            // operator opened then closed the box without changing anything).
            if (leavingEdit && _isIngestPreview)
                Text = _editableBody;
            OnChanged();
            OnChanged(nameof(EditBoxVisibility));
            OnChanged(nameof(MarkdownVisibility));
            OnChanged(nameof(EditButtonText));
        }
    }

    private string _editableBody = "";
    /// <summary>The cleaned article body the operator edits (TwoWay-bound box).</summary>
    public string EditableBody
    {
        get => _editableBody;
        set { if (_editableBody != value) { _editableBody = value; OnChanged(); } }
    }

    public string EditButtonText => IsEditing ? "Done editing" : "Edit";
    public Visibility IngestActionsVisibility =>
        IsIngestPreview ? Visibility.Visible : Visibility.Collapsed;
    public Visibility EditBoxVisibility =>
        IsIngestPreview && IsEditing ? Visibility.Visible : Visibility.Collapsed;
    // The rendered preview hides only while the edit box is open; normal
    // assistant turns (IsIngestPreview=false) always render.
    public Visibility MarkdownVisibility =>
        IsIngestPreview && IsEditing ? Visibility.Collapsed : Visibility.Visible;

    // ── Follow-up action buttons (#712) ──────────────────────────────────
    // A reply can carry follow-up buttons driven by one discriminator:
    //   "image"         → Edit / Save (ActionId is the generated-image id)
    //   "dispatch_plan" → Approve / Reject (ActionId empty)
    // Empty → no action row. Mirrors the IsIngestPreview flag pattern.

    private string _actionKind = "";
    /// <summary>"image" | "dispatch_plan" | "" — which follow-up buttons to show.</summary>
    public string ActionKind
    {
        get => _actionKind;
        set
        {
            if (_actionKind == value) return;
            _actionKind = value;
            OnChanged();
            OnChanged(nameof(ImageActionsVisibility));
            OnChanged(nameof(DispatchPlanActionsVisibility));
        }
    }

    /// <summary>The generated-image id for image actions (empty otherwise).</summary>
    public string ActionId { get; set; } = "";

    public Visibility ImageActionsVisibility =>
        ActionKind == "image" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility DispatchPlanActionsVisibility =>
        ActionKind == "dispatch_plan" ? Visibility.Visible : Visibility.Collapsed;

    /// <summary>Append a streamed token and notify.</summary>
    public void Append(string fragment)
    {
        _text += fragment;
        OnChanged(nameof(Text));
        OnChanged(nameof(TextVisibility));
        OnChanged(nameof(PlayVisibility));
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
